from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView

from lead.permissions import carteras_visibles
from .forms import CarteraForm, SubcarteraForm
from .models import Cartera, Subcartera

# Crear/editar carteras y subcarteras: solo admin/owner (el supervisor las gestiona, no las crea).
CAN_MANAGE_CARTERAS = ('admin', 'owner')


class CarteraManageRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not hasattr(request.user, 'userprofile') or request.user.userprofile.user_type not in CAN_MANAGE_CARTERAS:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class CarteraListView(LoginRequiredMixin, ListView):
    model = Cartera
    context_object_name = 'carteras'

    def get_queryset(self):
        # Un supervisor solo ve sus carteras; admin/owner todas.
        return carteras_visibles(self.request.user)


class CarteraDetailView(LoginRequiredMixin, DetailView):
    model = Cartera
    context_object_name = 'cartera'

    def get_queryset(self):
        return carteras_visibles(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['subcarteras'] = self.object.subcarteras.all()
        context['subcartera_form'] = SubcarteraForm()
        return context


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
