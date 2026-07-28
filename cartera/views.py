from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import ListView, DetailView, CreateView

from lead.permissions import carteras_visibles, es_admin_owner, es_supervisor
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
        # Un supervisor solo ve sus carteras; admin/owner todas. Los totales van en el mismo
        # query (un solo join subcarteras->leads, sin fan-out entre Sum y Count).
        return carteras_visibles(self.request.user).annotate(
            total_saldo_insoluto=Sum('subcarteras__leads__saldo_insoluto'),
            n_leads=Count('subcarteras__leads', distinct=True),
        )


class CarteraDetailView(CarteraViewRequiredMixin, DetailView):
    model = Cartera
    context_object_name = 'cartera'

    def get_queryset(self):
        return carteras_visibles(self.request.user)

    def get_context_data(self, **kwargs):
        from actions.models import Resultado, Medio
        context = super().get_context_data(**kwargs)
        context['subcarteras'] = self.object.subcarteras.all()
        context['subcartera_form'] = SubcarteraForm()
        context['puede_eliminar'] = _puede_eliminar_cartera(self.request.user, self.object)

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
