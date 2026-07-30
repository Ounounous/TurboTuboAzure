from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import ListView, DetailView, CreateView

from lead.permissions import carteras_visibles, es_admin_owner, es_supervisor, subcarteras_visibles
from .forms import CarteraForm, SubcarteraForm
from .models import Cartera, Subcartera
from .services import eliminar_cartera

# Crear/editar carteras y subcarteras: solo admin/owner (el supervisor las gestiona, no las crea).
CAN_MANAGE_CARTERAS = ('admin', 'owner')


class CarteraManageRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not hasattr(request.user, 'userprofile') or request.user.userprofile.user_type not in CAN_MANAGE_CARTERAS:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class CarteraViewRequiredMixin(LoginRequiredMixin):
    """Ver carteras (lista/detalle) es para admin/owner/supervisor -- un cobrador no navega
    carteras, solo sus leads (mismo criterio que oculta el link en el nav)."""
    def dispatch(self, request, *args, **kwargs):
        if not es_supervisor(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def _puede_eliminar_cartera(user, cartera):
    """admin/owner pueden eliminar cualquier cartera; un supervisor solo la que el mismo creo."""
    if es_admin_owner(user):
        return True
    return es_supervisor(user) and cartera.created_by_id == user.pk


class CarteraListView(CarteraViewRequiredMixin, ListView):
    model = Cartera
    context_object_name = 'carteras'

    def get_queryset(self):
        # Un supervisor solo ve sus carteras; admin/owner todas. Los totales se filtran a SOLO
        # las subcarteras visibles del usuario: sin el filter=, una cartera con varias
        # subcarteras (ej. Tanner con una por supervisor) mostraria el total combinado de TODAS
        # a cualquier supervisor que viera la fila, aunque solo la vea porque supervisa una.
        visibles = subcarteras_visibles(self.request.user)
        return carteras_visibles(self.request.user).annotate(
            total_saldo_insoluto=Sum('subcarteras__leads__saldo_insoluto', filter=Q(subcarteras__in=visibles)),
            n_leads=Count('subcarteras__leads', filter=Q(subcarteras__in=visibles), distinct=True),
        )


class CarteraDetailView(CarteraViewRequiredMixin, DetailView):
    model = Cartera
    context_object_name = 'cartera'

    def get_queryset(self):
        return carteras_visibles(self.request.user)

    def get_context_data(self, **kwargs):
        from actions.models import Resultado, Medio
        context = super().get_context_data(**kwargs)
        # Solo las subcarteras que el usuario supervisa dentro de esta cartera (admin/owner: todas).
        # Una cartera con varias subcarteras (ej. Tanner con una por supervisor) no debe mostrarle
        # a un supervisor las subcarteras -- y sus clientes -- de otro.
        context['subcarteras'] = subcarteras_visibles(self.request.user).filter(
            cartera=self.object
        ).annotate(n_leads=Count('leads'))
        context['subcartera_form'] = SubcarteraForm()
        context['puede_eliminar'] = _puede_eliminar_cartera(self.request.user, self.object)
        # Crear/eliminar subcarteras y cambiar cual es la predeterminada: solo admin/owner (mismo
        # criterio que crear subcarteras -- CarteraManageRequiredMixin), no el supervisor que
        # creo la cartera.
        context['puede_gestionar_subcarteras'] = es_admin_owner(self.request.user)

        # Árbol de decisiones
        context['medios'] = Medio.objects.filter(cartera=self.object).order_by('nombre')
        context['resultados'] = Resultado.objects.filter(cartera=self.object).order_by('nombre')

        return context


class CarteraDeleteView(CarteraViewRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        # Sin filtrar por carteras_visibles: el permiso de borrado es "admin/owner o quien la
        # creo", independiente de si hoy sigue apareciendo en su lista de carteras supervisadas
        # (esa asignacion la puede cambiar otro admin despues via el dashboard de Configuracion).
        cartera = get_object_or_404(Cartera, pk=pk)
        if not _puede_eliminar_cartera(request.user, cartera):
            raise PermissionDenied
        nombre = cartera.nombre
        eliminar_cartera(cartera)
        messages.success(
            request,
            f'Cartera "{nombre}" eliminada junto con sus leads y gestiones. '
            'Las grabaciones de llamadas se conservaron (retención legal).',
        )
        return redirect('cartera:list')


class CarteraCreateView(CarteraManageRequiredMixin, CreateView):
    model = Cartera
    form_class = CarteraForm
    success_url = reverse_lazy('cartera:list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, 'Cartera creada')
        return response


class SubcarteraCreateView(CarteraManageRequiredMixin, CreateView):
    model = Subcartera
    form_class = SubcarteraForm

    def dispatch(self, request, *args, **kwargs):
        self.cartera = get_object_or_404(Cartera, pk=kwargs['cartera_pk'])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.cartera = self.cartera
        response = super().form_valid(form)
        messages.success(self.request, 'Subcartera creada')
        return response

    def get_success_url(self):
        return reverse_lazy('cartera:detail', kwargs={'pk': self.cartera.pk})


class SubcarteraDeleteView(CarteraManageRequiredMixin, View):
    """Elimina una subcartera vacia. Bloqueada si: tiene clientes (Lead.subcartera es PROTECT --
    borrarla igual reventaria con un error feo sin este chequeo previo), es la subcartera por
    defecto (romperia las cargas de clientes sin subcartera explicita -- primero hay que marcar
    otra como predeterminada), o es la unica subcartera de la cartera (para eso se elimina la
    cartera completa, no la subcartera)."""
    def post(self, request, cartera_pk, pk, *args, **kwargs):
        subcartera = get_object_or_404(Subcartera, pk=pk, cartera_id=cartera_pk)
        if subcartera.leads.exists():
            messages.error(
                request,
                f'No se puede eliminar "{subcartera.nombre}": todavía tiene clientes asignados.',
            )
        elif subcartera.es_default:
            messages.error(
                request,
                f'"{subcartera.nombre}" es la subcartera por defecto. Marca otra como '
                'predeterminada antes de eliminarla.',
            )
        elif subcartera.cartera.subcarteras.count() <= 1:
            messages.error(
                request,
                'No puedes eliminar la única subcartera de una cartera. Si ya no la necesitas, '
                'elimina la cartera completa.',
            )
        else:
            nombre = subcartera.nombre
            subcartera.delete()
            messages.success(request, f'Subcartera "{nombre}" eliminada.')
        return redirect('cartera:detail', pk=cartera_pk)


class AsignarArbolView(CarteraManageRequiredMixin, View):
    """
    Asigna a esta cartera una de las 3 plantillas de arbol de gestiones (Galgo/Tanner/Nuevo
    Capital). Solo admin/owner, y solo UNA vez: en esta version no hay forma de cambiarlo desde
    la web (evita dejar el arbol en un estado ambiguo, mitad una plantilla mitad otra). Una
    version futura permitira editar nodos sueltos sin reasignar todo.
    """
    def post(self, request, pk, *args, **kwargs):
        from django.utils import timezone
        from actions.arbol_templates import APLICAR_POR_TIPO, REQUIERE_EXCEL

        cartera = get_object_or_404(Cartera, pk=pk)

        if cartera.arbol_tipo:
            messages.error(
                request,
                f'Esta cartera ya tiene un árbol asignado ({cartera.get_arbol_tipo_display()}). '
                'No se puede cambiar en esta versión.',
            )
            return redirect('cartera:detail', pk=cartera.pk)

        tipo = request.POST.get('arbol_tipo')
        if tipo not in APLICAR_POR_TIPO:
            messages.error(request, 'Elige un árbol válido (Galgo, Tanner o Nuevo Capital).')
            return redirect('cartera:detail', pk=cartera.pk)

        excel_file = request.FILES.get('excel_file')
        if tipo in REQUIERE_EXCEL:
            if not excel_file:
                messages.error(request, 'Ese árbol necesita que subas el Excel de origen.')
                return redirect('cartera:detail', pk=cartera.pk)
            if excel_file.size > 10 * 1024 * 1024:
                messages.error(request, 'El archivo supera el máximo de 10 MB.')
                return redirect('cartera:detail', pk=cartera.pk)

        try:
            if tipo in REQUIERE_EXCEL:
                stats = APLICAR_POR_TIPO[tipo](cartera, excel_file)
            else:
                stats = APLICAR_POR_TIPO[tipo](cartera)
        except Exception as exc:
            messages.error(request, f'No se pudo aplicar el árbol: {exc}')
            return redirect('cartera:detail', pk=cartera.pk)

        cartera.arbol_tipo = tipo
        cartera.arbol_asignado_at = timezone.now()
        cartera.arbol_asignado_por = request.user
        cartera.save(update_fields=['arbol_tipo', 'arbol_asignado_at', 'arbol_asignado_por'])

        messages.success(
            request,
            f'Árbol "{cartera.get_arbol_tipo_display()}" asignado: '
            f'{stats["medios_creados"]} medio(s), {stats["resultados_creados"]} resultado(s) nuevo(s), '
            f'{stats["resultados_actualizados"]} actualizado(s).',
        )
        return redirect('cartera:detail', pk=cartera.pk)


class SubcarteraSetDefaultView(CarteraManageRequiredMixin, View):
    """Cambia cual subcartera es la predeterminada dentro de una cartera (destino de las cargas
    de clientes que no especifican subcartera explicita)."""
    def post(self, request, cartera_pk, pk, *args, **kwargs):
        subcartera = get_object_or_404(Subcartera, pk=pk, cartera_id=cartera_pk)
        with transaction.atomic():
            Subcartera.objects.filter(cartera_id=cartera_pk).update(es_default=False)
            subcartera.es_default = True
            subcartera.save(update_fields=['es_default'])
        messages.success(request, f'"{subcartera.nombre}" es ahora la subcartera por defecto.')
        return redirect('cartera:detail', pk=cartera_pk)
