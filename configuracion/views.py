from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from cartera.models import Subcartera
from lead.permissions import es_admin_owner, es_supervisor
from suspensiones.models import RetentionSettings
from team.forms import TeamForm
from team.models import Team
from userprofile.forms import PbxCredentialsForm
from userprofile.models import Userprofile

from .forms import CrearUsuarioForm


class ConfiguracionRequiredMixin(LoginRequiredMixin):
    """Solo admin/owner: configurar usuarios/permisos y retencion no es cosa de supervisor."""
    def dispatch(self, request, *args, **kwargs):
        if not es_admin_owner(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def _en_alcance(actor, target_user):
    """Un admin/owner puede editar a cualquiera; un supervisor solo a los de su propio equipo."""
    if es_admin_owner(actor):
        return True
    team = getattr(actor.userprofile, 'active_team', None)
    target_profile = getattr(target_user, 'userprofile', None)
    return bool(team and target_profile and target_profile.active_team_id == team.id)


class ConfiguracionHomeView(ConfiguracionRequiredMixin, View):
    template_name = 'configuracion/index.html'

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name)


class UsuariosPermisosView(LoginRequiredMixin, View):
    """Gestion de usuarios. admin/owner: todo (roles, equipos, crear, supervisores por subcartera,
    y datos de contacto/SIP de cualquier usuario). supervisor: solo datos de contacto (RUT, correo,
    telefono) y credenciales SIP de los usuarios de su propio equipo. cobrador: sin acceso."""
    template_name = 'configuracion/usuarios_permisos.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not es_supervisor(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        es_admin = es_admin_owner(request.user)
        if es_admin:
            usuarios = User.objects.select_related('userprofile').order_by('username')
        else:
            # supervisor: solo los miembros de su equipo activo.
            team = getattr(request.user.userprofile, 'active_team', None)
            usuarios = (
                team.members.select_related('userprofile').order_by('username')
                if team else User.objects.none()
            )
        contexto = {
            'usuarios': usuarios,
            'tipos': Userprofile.USER_TYPES,
            'es_admin': es_admin,
        }
        if es_admin:
            contexto.update({
                'subcarteras': Subcartera.objects.select_related('cartera').prefetch_related('supervisores')
                    .order_by('cartera__nombre', 'nombre'),
                'supervisores_disponibles': User.objects.filter(
                    userprofile__user_type__in=('supervisor', 'admin', 'owner')
                ).order_by('username'),
                'equipos': Team.objects.order_by('name'),
                'crear_usuario_form': CrearUsuarioForm(),
            })
        return render(request, self.template_name, contexto)

    def post(self, request, *args, **kwargs):
        accion = request.POST.get('accion')
        es_admin = es_admin_owner(request.user)

        # Acciones de contacto y SIP: disponibles para supervisor+ (acotadas a su equipo).
        if accion in ('editar_contacto', 'configurar_sip'):
            user = get_object_or_404(User, pk=request.POST.get('user_id'))
            if not _en_alcance(request.user, user):
                raise PermissionDenied
            userprofile, _ = Userprofile.objects.get_or_create(user=user)

            if accion == 'editar_contacto':
                # Actualiza solo los campos presentes en el POST (permite formularios separados).
                if 'email' in request.POST:
                    user.email = request.POST.get('email', '').strip()
                    user.save(update_fields=['email'])
                if 'rut' in request.POST:
                    userprofile.rut = request.POST.get('rut', '').strip()
                if 'telefono' in request.POST:
                    userprofile.telefono = request.POST.get('telefono', '').strip()
                userprofile.save()
                messages.success(request, f'Datos de contacto de {user.username} actualizados.')
            else:  # configurar_sip
                form = PbxCredentialsForm(request.POST, userprofile=userprofile)
                if form.is_valid():
                    form.save()
                    messages.success(request, f'Credenciales SIP de {user.username} guardadas.')
                else:
                    for field, errores in form.errors.items():
                        for error in errores:
                            messages.error(request, f'SIP {field}: {error}')
            return redirect('configuracion:usuarios_permisos')

        # El resto de las acciones son solo de admin/owner.
        if not es_admin:
            raise PermissionDenied

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
                # La clave que puso el admin es TEMPORAL: el usuario debera cambiarla en su primer
                # ingreso (ForcePasswordChangeMiddleware lo obliga).
                userprofile.must_change_password = True
                userprofile.save(update_fields=['active_team', 'user_type', 'must_change_password'])
                messages.success(
                    request,
                    f'Usuario "{user.username}" creado como {dict(Userprofile.USER_TYPES)[userprofile.user_type]}. '
                    'Entrégale la contraseña temporal; se le pedirá cambiarla en su primer ingreso.'
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
            subcartera = get_object_or_404(Subcartera, pk=request.POST.get('subcartera_id'))
            ids = request.POST.getlist('supervisores')
            usuarios_validos = User.objects.filter(
                pk__in=ids, userprofile__user_type__in=('supervisor', 'admin', 'owner')
            )
            subcartera.supervisores.set(usuarios_validos)
            messages.success(
                request,
                f'{subcartera.cartera.nombre} / {subcartera.nombre}: '
                f'{usuarios_validos.count()} supervisor(es) asignado(s).'
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
            config.dias_retencion_accesos = int(request.POST.get('dias_retencion_accesos'))
            config.dias_retencion_asignaciones = int(request.POST.get('dias_retencion_asignaciones'))
        except (TypeError, ValueError):
            messages.error(request, 'Los plazos deben ser números enteros.')
            return redirect('configuracion:retencion')

        if min(config.dias_purga_terminado, config.dias_purga_desasignado,
               config.dias_retencion_statuslog, config.dias_retencion_accesos,
               config.dias_retencion_asignaciones) < 1:
            messages.error(request, 'Los plazos deben ser mayores a 0.')
            return redirect('configuracion:retencion')

        config.updated_by = request.user
        config.save()
        messages.success(request, 'Configuración de retención actualizada.')
        return redirect('configuracion:retencion')


class RegistrosAccionesView(ConfiguracionRequiredMixin, View):
    """Registro de accesos a datos de deudores (Ley 20.575). Solo admin/owner. Lista liviana:
    ultimos 300 accesos, con filtros por usuario, tipo de accion y fecha."""
    template_name = 'configuracion/registros_acciones.html'

    def get(self, request, *args, **kwargs):
        from django.utils.dateparse import parse_date
        from .models import AccessLog

        registros = AccessLog.objects.select_related('user', 'lead')
        f_usuario = request.GET.get('usuario', '').strip()
        f_accion = request.GET.get('accion', '').strip()
        f_fecha = request.GET.get('fecha', '').strip()
        if f_usuario:
            registros = registros.filter(user__username__icontains=f_usuario)
        if f_accion:
            registros = registros.filter(action_type=f_accion)
        if f_fecha:
            parsed = parse_date(f_fecha)
            if parsed:
                registros = registros.filter(timestamp__date=parsed)

        return render(request, self.template_name, {
            'registros': registros[:300],
            'acciones': AccessLog.CHOICES_ACCION,
            'f_usuario': f_usuario,
            'f_accion': f_accion,
            'f_fecha': f_fecha,
        })
