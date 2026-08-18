"""
Vistas de configuracion de reportes automaticos (ver actions/models.py: ReporteAutomaticoConfig).
Archivo aparte de actions/views.py (ya grande) -- montadas bajo cartera/urls.py porque
conceptualmente viven en el detalle de cartera, mismo criterio que AsignarArbolView.
"""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import UpdateView

from cartera.models import Cartera
from cartera.views import CarteraManageRequiredMixin

from .forms_reportes import ReporteAutomaticoConfigForm
from .models import ReporteAutomaticoConfig
from .tasks import enviar_reporte_automatico


class ReporteAutomaticoListCreateView(CarteraManageRequiredMixin, View):
    """GET: lista + form vacio para crear. POST: crea una config nueva."""

    def _cartera(self, cartera_pk):
        return get_object_or_404(Cartera, pk=cartera_pk)

    def get(self, request, cartera_pk, *args, **kwargs):
        cartera = self._cartera(cartera_pk)
        form = ReporteAutomaticoConfigForm(cartera=cartera)
        return render(request, 'cartera/reportes_automaticos_form.html', {
            'cartera': cartera, 'form': form, 'config': None,
        })

    def post(self, request, cartera_pk, *args, **kwargs):
        cartera = self._cartera(cartera_pk)
        form = ReporteAutomaticoConfigForm(request.POST, cartera=cartera)
        if form.is_valid():
            config = form.save(commit=False)
            config.cartera = cartera
            config.creado_por = request.user
            config.save()
            form.save_m2m()
            messages.success(request, 'Reporte automático creado.')
            return redirect('cartera:detail', pk=cartera.pk)
        return render(request, 'cartera/reportes_automaticos_form.html', {
            'cartera': cartera, 'form': form, 'config': None,
        })


class ReporteAutomaticoUpdateView(CarteraManageRequiredMixin, UpdateView):
    model = ReporteAutomaticoConfig
    form_class = ReporteAutomaticoConfigForm
    template_name = 'cartera/reportes_automaticos_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.cartera = get_object_or_404(Cartera, pk=kwargs['cartera_pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return ReporteAutomaticoConfig.objects.filter(cartera=self.cartera)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['cartera'] = self.cartera
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['cartera'] = self.cartera
        context['config'] = self.object
        return context

    def form_valid(self, form):
        form.instance.actualizado_por = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, 'Reporte automático actualizado.')
        return response

    def get_success_url(self):
        return reverse('cartera:detail', kwargs={'pk': self.cartera.pk})


class ReporteAutomaticoToggleView(CarteraManageRequiredMixin, View):
    def post(self, request, cartera_pk, pk, *args, **kwargs):
        config = get_object_or_404(ReporteAutomaticoConfig, pk=pk, cartera_id=cartera_pk)
        config.activo = not config.activo
        config.actualizado_por = request.user
        config.save(update_fields=['activo', 'actualizado_por'])
        messages.success(request, f'Reporte automático {"activado" if config.activo else "desactivado"}.')
        return redirect('cartera:detail', pk=cartera_pk)


class ReporteAutomaticoDeleteView(CarteraManageRequiredMixin, View):
    def post(self, request, cartera_pk, pk, *args, **kwargs):
        config = get_object_or_404(ReporteAutomaticoConfig, pk=pk, cartera_id=cartera_pk)
        config.delete()
        messages.success(request, 'Reporte automático eliminado.')
        return redirect('cartera:detail', pk=cartera_pk)


class ReporteAutomaticoTestSendView(CarteraManageRequiredMixin, View):
    """"Enviar de prueba ahora": encola el envio de inmediato, sin esperar el horario programado.
    Respeta rango_pendiente (el rango pendiente real de esa config), ignora hora_envio/periodicidad."""
    def post(self, request, cartera_pk, pk, *args, **kwargs):
        config = get_object_or_404(ReporteAutomaticoConfig, pk=pk, cartera_id=cartera_pk)
        enviar_reporte_automatico.delay(config.pk)
        messages.success(
            request,
            f'Envío de prueba encolado para "{config}". Revisa el estado ("Último envío") en unos segundos.',
        )
        return redirect('cartera:detail', pk=cartera_pk)
