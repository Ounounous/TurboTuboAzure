from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from cartera.models import Cartera
from lead.permissions import es_admin_owner
from suspensiones.models import RetentionSettings
from team.forms import TeamForm
from team.models import Team
from userprofile.models import Userprofile

from .forms import CrearUsuarioForm


class ConfiguracionRequiredMixin(LoginRequiredMixin):
    """Solo admin/owner: configurar usuarios/permisos y retencion no es cosa de supervisor."""
    def dispatch(self, request, *args, **kwargs):
        if not es_admin_owner(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class ConfiguracionHomeView(ConfiguracionRequiredMixin, View):
    template_name = 'configuracion/index.html'

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name)


class UsuariosPermisosView(ConfiguracionRequiredMixin, View):
    template_name = 'configuracion/usuarios_permisos.html'

    def get(self, request, *args, **kwargs):
        usuarios = User.objects.select_related('userprofile').order_by('username')
        carteras = Cartera.objects.prefetch_related('supervisores').order_by('nombre')
        supervisores_disponibles = User.objects.filter(
            userprofile__user_type__in=('supervisor', 'admin', 'owner')
        ).order_by('username')
        return render(request, self.template_name, {
            'usuarios': usuarios,
            'carteras': carteras,
            'supervisores_disponibles': supervisores_disponibles,
            'tipos': Userprofile.USER_TYPES,
            'equipos': Team.objects.order_by('name'),
            'crear_usuario_form': CrearUsuarioForm(),
        })

    def post(self, request, *args, **kwargs):
        accion = request.POST.get('accion')

        if accion == 'crear_usuario':
            form = CrearUsuarioForm(request.POST)
            if form.is_valid():
                team = request.user.userprofile.active_team
                user = form.save()
                team.members.add(user)
                # El signal post_save de User (userprofile/models.py) ya crea el Userprofile
                # -- get_or_create en vez de create() para no chocar con el que el signal
                # acaba de dejar.
                userprofile, _ = Userprofile.objects.get_or_create(user=user)
                userprofile.active_team = team
                userprofile.user_type = form.cleaned_data['user_type']
                userprofile.save(update_fields=['active_team', 'user_type'])
                messages.success(
                    request,
                    f'Usuario "{user.username}" creado como {dict(Userprofile.USER_TYPES)[userprofile.user_type]}.'
                )
            else:
                for field, errores in form.errors.items():
                    for error in errores:
                        messages.error(request, f'{field}: {error}')

        elif accion == 'cambiar_tipo':
            user = get_object_or_404(User, pk=request.POST.get('user_id'))
            nuevo_tipo = request.POST.get('user_type')
            if nuevo_tipo not in dict(Userprofile.USER_TYPES):
                messages.error(request, 'Tipo de usuario inválido.')
            elif user.pk == request.user.pk and nuevo_tipo not in ('admin', 'owner'):
                # No te puedes sacar a ti mismo el acceso a esta pantalla sin querer.
                messages.error(request, 'No puedes quitarte a ti mismo el rol de admin/owner desde aquí.')
            else:
                userprofile, _ = Userprofile.objects.get_or_create(user=user)
                userprofile.user_type = nuevo_tipo
                userprofile.save(update_fields=['user_type'])
                messages.success(request, f'{user.username} ahora es {dict(Userprofile.USER_TYPES)[nuevo_tipo]}.')

        elif accion == 'cambiar_equipo':
            user = get_object_or_404(User, pk=request.POST.get('user_id'))
            team_id = request.POST.get('team_id')
            userprofile, _ = Userprofile.objects.get_or_create(user=user)
            equipo_anterior = userprofile.active_team

            if not team_id:
                if equipo_anterior:
                    equipo_anterior.members.remove(user)
                userprofile.active_team = None
                userprofile.save(update_fields=['active_team'])
                messages.success(request, f'{user.username} ya no pertenece a ningún equipo.')
            else:
                nuevo_equipo = get_object_or_404(Team, pk=team_id)
                if equipo_anterior:
                    equipo_anterior.members.remove(user)
                nuevo_equipo.members.add(user)
                userprofile.active_team = nuevo_equipo
                userprofile.save(update_fields=['active_team'])
                messages.success(request, f'{user.username} ahora pertenece al equipo "{nuevo_equipo.name}".')

        elif accion == 'asignar_supervisores':
            cartera = get_object_or_404(Cartera, pk=request.POST.get('cartera_id'))
            ids = request.POST.getlist('supervisores')
            usuarios_validos = User.objects.filter(
                pk__in=ids, userprofile__user_type__in=('supervisor', 'admin', 'owner')
            )
            cartera.supervisores.set(usuarios_validos)
            messages.success(
                request,
                f'{cartera.nombre}: {usuarios_validos.count()} supervisor(es) asignado(s).'
            )

        else:
            messages.error(request, 'Acción inválida.')

        return redirect('configuracion:usuarios_permisos')


class EquipoView(ConfiguracionRequiredMixin, View):
    """Nombre del equipo y sus miembros. Opera siempre sobre el equipo activo del admin que
    entra -- mismo equipo al que "Crear usuario" (UsuariosPermisosView) agrega gente nueva."""
    template_name = 'configuracion/equipo.html'

    def get(self, request, *args, **kwargs):
        team = request.user.userprofile.active_team
        miembros = (
            team.members.select_related('userprofile').order_by('username') if team else User.objects.none()
        )
        return render(request, self.template_name, {
            'team': team,
            'miembros': miembros,
            'team_form': TeamForm(instance=team) if team else None,
            'crear_equipo_form': TeamForm(),
        })

    def post(self, request, *args, **kwargs):
        team = request.user.userprofile.active_team
        if not team:
            messages.error(request, 'No tienes un equipo activo.')
            return redirect('configuracion:equipo')

        accion = request.POST.get('accion')

        if accion == 'renombrar':
            form = TeamForm(request.POST, instance=team)
            if form.is_valid():
                form.save()
                messages.success(request, 'Nombre del equipo actualizado.')
            else:
                messages.error(request, 'Nombre inválido.')

        elif accion == 'quitar_miembro':
            user = get_object_or_404(User, pk=request.POST.get('user_id'), teams=team)
            if user.pk == request.user.pk:
                # Evita que un admin se saque a si mismo del equipo sin querer y se quede
                # sin acceso a nada (mismo espiritu que el auto-bloqueo de rol en Usuarios).
                messages.error(request, 'No puedes quitarte a ti mismo del equipo desde aquí.')
            else:
                team.members.remove(user)
                userprofile = getattr(user, 'userprofile', None)
                if userprofile and userprofile.active_team_id == team.pk:
                    userprofile.active_team = None
                    userprofile.save(update_fields=['active_team'])
                messages.success(request, f'{user.username} ya no es parte del equipo.')

        else:
            messages.error(request, 'Acción inválida.')

        return redirect('configuracion:equipo')


class RetencionDatosView(ConfiguracionRequiredMixin, View):
    template_name = 'configuracion/retencion.html'

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {'config': RetentionSettings.get_solo()})

    def post(self, request, *args, **kwargs):
        config = RetentionSettings.get_solo()
        try:
            config.dias_purga_terminado = int(request.POST.get('dias_purga_terminado'))
            config.dias_purga_desasignado = int(request.POST.get('dias_purga_desasignado'))
            config.dias_retencion_statuslog = int(request.POST.get('dias_retencion_statuslog'))
        except (TypeError, ValueError):
            messages.error(request, 'Los plazos deben ser números enteros.')
            return redirect('configuracion:retencion')

        if min(config.dias_purga_terminado, config.dias_purga_desasignado, config.dias_retencion_statuslog) < 1:
            messages.error(request, 'Los plazos deben ser mayores a 0.')
            return redirect('configuracion:retencion')

        config.updated_by = request.user
        config.save()
        messages.success(request, 'Configuración de retención actualizada.')
        return redirect('configuracion:retencion')
