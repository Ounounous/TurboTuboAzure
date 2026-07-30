from io import BytesIO

import openpyxl
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

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

        # Alcance por rol: un supervisor solo ve los leads de sus carteras.
        from lead.permissions import leads_visibles
        visibles = leads_visibles(request.user)
        counts = {row['activo']: row['n'] for row in visibles.values('activo').annotate(n=Count('id'))}
        tarjetas = [
            {'valor': val, 'label': label, 'count': counts.get(val, 0), 'active': estado == val}
            for val, label in Lead.CHOICES_ACTIVO
        ]

        leads = (
            visibles.filter(activo=estado)
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
        from lead.permissions import leads_visibles
        lead = get_object_or_404(leads_visibles(request.user), pk=pk)
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


LIFECYCLE_UPLOAD_ALIASES = {
    'cartera': 'cartera', 'subcartera': 'subcartera',
    'op': 'op', 'operacion': 'op', 'id': 'op',
    'accion': 'accion', 'action': 'accion',
    'motivo': 'motivo', 'reason': 'motivo',
}


class SuspensionesTemplateView(SupervisorRequiredMixin, View):
    """Plantilla Excel para la carga masiva de cambios de ciclo de vida (suspender/desasignar/reactivar)."""
    def get(self, request, *args, **kwargs):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Suspensiones'
        ws.append(['cartera', 'subcartera', 'op', 'accion', 'motivo'])
        ws.append(['CARTERA-EJEMPLO', 'SUBCARTERA-EJEMPLO', 'OP-EJEMPLO', 'suspender', 'no ubicable'])

        output = BytesIO()
        wb.save(output)
        output.seek(0)
        response = HttpResponse(
            content=output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename=plantilla_suspensiones.xlsx'
        return response


class BulkLifecycleUploadView(SupervisorRequiredMixin, View):
    """Carga masiva: Excel con columnas CARTERA, SUBCARTERA, ID, ACCION, MOTIVO (opcional)."""

    # Campos que toca cada transicion (ver lead/lifecycle.py) -- se snapshotean antes de llamar
    # a la funcion, porque la mutacion + el save() ya los hace ella misma.
    CAMPOS_POR_ACCION = {
        'suspender': ['activo', 'suspendido_at', 'motivo_suspension'],
        'desasignar': ['activo', 'desasignado_at', 'assigned_to_id'],
        'reactivar': ['activo', 'suspendido_at', 'desasignado_at', 'terminado_at', 'datos_purgados_at', 'motivo_suspension'],
    }

    def post(self, request, *args, **kwargs):
        from core.bulk_upload import procesar_carga
        from core.carga_tracking import iniciar_lote, registrar_actualizacion_valores
        from lead.permissions import leads_visibles

        def validar_fila(fila, rownum):
            errores = []
            accion_norm = str(fila.get('accion') or '').strip().lower()
            if accion_norm not in ACCIONES:
                errores.append(f"acción '{fila.get('accion')}' inválida (usa suspender/desasignar/reactivar)")

            lead = find_lead(fila.get('cartera'), fila.get('subcartera'), fila.get('op'))
            if not lead:
                errores.append(
                    f"no se encontró lead OP={fila.get('op')} en Cartera={fila.get('cartera')}, "
                    f"Subcartera={fila.get('subcartera')}"
                )
            elif not leads_visibles(request.user, base=Lead.objects.filter(pk=lead.pk)).exists():
                errores.append(f"no tienes permiso sobre la cartera {fila.get('cartera')} (OP={fila.get('op')})")

            if errores:
                return None, errores
            return {'lead': lead, 'accion': accion_norm, 'motivo': str(fila.get('motivo') or '')}, []

        resultado = procesar_carga(
            request.FILES.get('excel_file'), LIFECYCLE_UPLOAD_ALIASES,
            ('cartera', 'subcartera', 'op', 'accion'), validar_fila,
            nombre_archivo='errores_suspensiones.xlsx',
        )
        if not resultado.ok:
            return resultado.respuesta_error

        excel_file = request.FILES.get('excel_file')
        with transaction.atomic():
            lote = iniciar_lote('suspensiones', request.user, archivo_nombre=getattr(excel_file, 'name', ''), total_filas=len(resultado.filas))
            for f in resultado.filas:
                lead = f['lead']
                campos = self.CAMPOS_POR_ACCION[f['accion']]
                antes = {c: getattr(lead, c) for c in campos}

                if f['accion'] == 'suspender':
                    suspender(lead, motivo=f['motivo'], changed_by=request.user)
                elif f['accion'] == 'desasignar':
                    desasignar(lead, changed_by=request.user)
                else:
                    reactivar(lead, changed_by=request.user)

                registrar_actualizacion_valores(lote, lead, {c: (antes[c], getattr(lead, c)) for c in campos})

        messages.success(request, f"Se aplicó la acción a {len(resultado.filas)} lead(s).")
        return redirect('suspensiones:index')
