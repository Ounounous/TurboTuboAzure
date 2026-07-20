from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from cartera.models import Cartera
from lead.permissions import es_admin_owner
from suspensiones.models import RetentionSettings
from userprofile.models import Userprofile


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
        })

    def post(self, request, *args, **kwargs):
        accion = request.POST.get('accion')

        if accion == 'cambiar_tipo':
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
