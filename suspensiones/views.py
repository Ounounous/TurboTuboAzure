from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from openpyxl import load_workbook

from demographics.views import find_lead
from lead.lifecycle import desasignar, reactivar, suspender
from lead.models import Lead

SUPERVISOR_TYPES = ('admin', 'owner', 'supervisor')

# Acciones validas del ciclo de vida (las que un supervisor puede aplicar a mano/por Excel).
# "terminar" no esta: terminado lo genera solo el status "al dia", no se marca a mano.
ACCIONES = {
    'suspender': suspender,
    'desasignar': desasignar,
    'reactivar': reactivar,
}


class SupervisorRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        userprofile = getattr(request.user, 'userprofile', None)
        if not userprofile or userprofile.user_type not in SUPERVISOR_TYPES:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def _aplicar(accion, lead, request):
    """Ejecuta una accion del ciclo de vida sobre un lead, con su motivo si aplica."""
    if accion == 'suspender':
        suspender(lead, motivo=request.POST.get('motivo', ''), changed_by=request.user)
    elif accion == 'desasignar':
        desasignar(lead, changed_by=request.user)
    elif accion == 'reactivar':
        reactivar(lead, changed_by=request.user)


class SuspensionesHomeView(SupervisorRequiredMixin, View):
    template_name = 'suspensiones/index.html'

    def get(self, request, *args, **kwargs):
        estado = request.GET.get('estado', Lead.SUSPENDIDO)
        if estado not in dict(Lead.CHOICES_ACTIVO):
            estado = Lead.SUSPENDIDO

        counts = {row['activo']: row['n'] for row in Lead.objects.values('activo').annotate(n=Count('id'))}
        tarjetas = [
            {'valor': val, 'label': label, 'count': counts.get(val, 0), 'active': estado == val}
            for val, label in Lead.CHOICES_ACTIVO
        ]

        leads = (
            Lead.objects.filter(activo=estado)
            .select_related('subcartera__cartera', 'assigned_to')
            .order_by('-suspendido_at', '-desasignado_at', '-terminado_at', 'name')[:300]
        )

        context = {
            'tarjetas': tarjetas,
            'estado': estado,
            'estado_label': dict(Lead.CHOICES_ACTIVO)[estado],
            'leads': leads,
            'es_activo': estado == Lead.ACTIVO,
        }
        return render(request, self.template_name, context)


class LeadLifecycleActionView(SupervisorRequiredMixin, View):
    """Suspender / desasignar / reactivar un lead. Usada desde la ficha y desde esta pantalla."""

    def post(self, request, pk, *args, **kwargs):
        lead = get_object_or_404(Lead, pk=pk)
        accion = request.POST.get('accion', '')
        if accion not in ACCIONES:
            messages.error(request, 'Acción inválida.')
        else:
            _aplicar(accion, lead, request)
            etiquetas = {'suspender': 'suspendido', 'desasignar': 'desasignado', 'reactivar': 'reactivado'}
            messages.success(request, f'{lead.op} {etiquetas[accion]}.')
        next_url = request.POST.get('next')
        if next_url:
            return redirect(next_url)
        return redirect('leads:detail', pk=lead.pk)


class BulkLifecycleUploadView(SupervisorRequiredMixin, View):
    """Carga masiva: Excel con columnas CARTERA, SUBCARTERA, ID, ACCION, MOTIVO (opcional)."""

    def post(self, request, *args, **kwargs):
        excel_file = request.FILES.get('excel_file')
        if not excel_file:
            messages.error(request, 'Debes subir un archivo Excel.')
            return redirect('suspensiones:index')

        wb = load_workbook(excel_file)
        sheet = wb.active

        aplicados, errores = 0, []
        for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            cartera, subcartera, op, accion, motivo = (list(row) + [None] * 5)[:5]
            if not cartera or not subcartera or not op or not accion:
                errores.append(f"Fila {row_number}: faltan datos (cartera, subcartera, ID o acción).")
                continue

            accion_norm = str(accion).strip().lower()
            if accion_norm not in ACCIONES:
                errores.append(f"Fila {row_number}: acción '{accion}' inválida (usa suspender/desasignar/reactivar).")
                continue

            lead = find_lead(cartera, subcartera, op)
            if not lead:
                errores.append(f"Fila {row_number}: no se encontró lead OP={op} en Cartera={cartera}, Subcartera={subcartera}.")
                continue

            if accion_norm == 'suspender':
                suspender(lead, motivo=str(motivo or ''), changed_by=request.user)
            elif accion_norm == 'desasignar':
                desasignar(lead, changed_by=request.user)
            else:
                reactivar(lead, changed_by=request.user)
            aplicados += 1

        if aplicados:
            messages.success(request, f'Se aplicó la acción a {aplicados} lead(s).')
        for error in errores[:20]:
            messages.error(request, error)
        if len(errores) > 20:
            messages.error(request, f'... y {len(errores) - 20} error(es) más.')

        return redirect('suspensiones:index')
