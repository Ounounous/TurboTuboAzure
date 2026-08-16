"""
Procesa un evento del webhook de escritura (Contrato API v1, sección 1.2) en el worker, nunca en
el proceso web -- Action.save() dispara compromiso + status + efecto demográfico + captura ML
dentro de su propia transacción (ver plan de riesgos, "carga sobre producción"). El receptor HTTP
(api/views.py::WebhookEventoView) solo valida firma + idempotencia y responde 202.

No se reimplementan las reglas de negocio: se llama Action.objects.create(...) con el mismo Medio/
Resultado que usaría un gestor humano -- resueltos por MapeoResultadoCampana, nunca por nombre
libre (ver CONTRATO_API_v1.md sección 3 y plan de riesgos sección 07, precaución Tanner nº1,
aplicada aquí también aunque esta fase solo habilita Galgo).
"""
import logging

from celery import shared_task
from django.db import InterfaceError, OperationalError
from django.utils import timezone

logger = logging.getLogger(__name__)

RETRY_DB = dict(
    autoretry_for=(OperationalError, InterfaceError),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)

# Fase 4 del plan solo habilita Galgo -- Tanner tiene dos archivos regulatorios de por medio
# (ver CONTRATO_API_v1.md sección 3.2 y plan de riesgos sección 07); se habilita en Fase 5 recién
# con las tres precauciones (código+tipo_contacto, bloqueo 129-153, no-regresión byte a byte).
CARTERAS_ARBOL_HABILITADO = {'galgo'}


@shared_task(**RETRY_DB)
def procesar_evento_webhook(job_id):
    from actions.models import Action
    from api.freno_demografico import verificar_freno
    from api.models import MapeoResultadoCampana, WebhookEventoJob
    from lead.models import Lead

    try:
        job = WebhookEventoJob.objects.select_related('cliente').get(pk=job_id)
    except WebhookEventoJob.DoesNotExist:
        logger.warning(f'procesar_evento_webhook: job {job_id} no existe (¿se borró?)')
        return

    if job.estado != WebhookEventoJob.PENDIENTE:
        logger.warning(f'procesar_evento_webhook: job {job_id} ya está en estado {job.estado}, se omite')
        return

    job.estado = WebhookEventoJob.PROCESANDO
    job.save(update_fields=['estado'])

    payload = job.payload
    try:
        lead = Lead.objects.select_related('subcartera__cartera').get(
            op=payload['op'], subcartera__cartera__in=job.cliente.carteras.all() or None,
        )
    except Lead.DoesNotExist:
        _rechazar(job, f'Lead con op={payload.get("op")!r} no encontrado o fuera del alcance de este cliente.')
        return
    except Lead.MultipleObjectsReturned:
        # No debería pasar (Lead.op no es unique globalmente, pero el scope de cartera del
        # cliente + el op deberían acotar a uno) -- si pasa, mejor rechazar que adivinar cuál.
        _rechazar(job, f'op={payload.get("op")!r} es ambiguo (más de un lead) dentro del alcance de este cliente.')
        return

    cartera = lead.subcartera.cartera
    if cartera.arbol_tipo not in CARTERAS_ARBOL_HABILITADO:
        _rechazar(job, f'La cartera "{cartera.nombre}" todavía no tiene escritura habilitada vía webhook (Fase 4 = solo Galgo).')
        return

    try:
        mapeo = MapeoResultadoCampana.objects.select_related('medio', 'resultado').get(
            cartera=cartera, canal=payload['canal'], resultado_corto=payload['resultado'],
        )
    except MapeoResultadoCampana.DoesNotExist:
        _rechazar(job, f'Sin mapeo configurado para cartera={cartera.nombre} canal={payload["canal"]} resultado={payload["resultado"]}.')
        return

    if verificar_freno(job.cliente, mapeo.resultado):
        job.estado = WebhookEventoJob.DETENIDO_FRENO
        job.detalle = 'Freno de efectos demográficos activo -- ver AccessLog y logs del worker.'
        job.finished_at = timezone.now()
        job.save(update_fields=['estado', 'detalle', 'finished_at'])
        return

    action = Action.objects.create(
        lead=lead, medio=mapeo.medio, resultado=mapeo.resultado, user=None,
        target=payload.get('target') or 'principal',
        origen=Action.ORIGEN_SALIENTE,
        comment=f'Vía webhook API (cliente: {job.cliente.nombre}, event_id: {job.event_id})',
    )

    job.action = action
    job.estado = WebhookEventoJob.APLICADO
    job.finished_at = timezone.now()
    job.save(update_fields=['action', 'estado', 'finished_at'])


def _rechazar(job, detalle):
    logger.warning(f'procesar_evento_webhook: job {job.pk} rechazado -- {detalle}')
    job.estado = job.RECHAZADO
    job.detalle = detalle
    job.finished_at = timezone.now()
    job.save(update_fields=['estado', 'detalle', 'finished_at'])
