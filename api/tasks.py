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
from django.db import InterfaceError, OperationalError, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

RETRY_DB = dict(
    autoretry_for=(OperationalError, InterfaceError),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)

# Fase 5 habilita Tanner (además de Galgo, Fase 4) con las tres precauciones del plan de riesgos
# sección 07: resultado resuelto por código+tipo_contacto (nunca nombre libre, ver
# MapeoResultadoCampana + sembrar_mapeo_tanner.py), bloqueo defensivo de 129-153 (abajo), y
# no-regresión byte a byte verificada aparte (test_no_regresion_tanner.py) antes de habilitar.
# Nuevo Capital todavía no tiene precauciones definidas -- se agrega en su propia fase.
CARTERAS_ARBOL_HABILITADO = {'galgo', 'tanner'}

CANALES_TELEFONICOS = {'sms', 'whatsapp', 'ivr'}


def _resolver_contacto(lead, canal, target):
    """
    Devuelve (phone, email) para adjuntar al Action -- sin esto, aplicar_efecto_demografico()
    (actions/status_logic.py) nunca tiene un phone_id/email sobre el que actuar, y el freno
    demográfico (api/freno_demografico.py) nunca puede contar nada real (auditoría, hallazgo 2).
    Solo resuelve target='principal' (el único que usa el emisor de cobranza-saas hoy); target
    'aval' queda sin resolver -- el Action se crea igual, solo sin efecto demográfico asociado,
    mismo comportamiento que antes de este fix.
    """
    from demographics.models import IDDemographics, Phone

    if target != 'principal':
        return None, None

    if canal in CANALES_TELEFONICOS:
        phone = Phone.objects.filter(
            lead=lead, phone_type=Phone.PRINCIPAL, phone_number_status=Phone.ACTIVE,
        ).first()
        return phone, None

    if canal == 'email':
        id_demo = IDDemographics.objects.filter(lead=lead).exclude(principal_email='').first()
        return None, (id_demo.principal_email if id_demo else None)

    return None, None


@shared_task(**RETRY_DB)
def procesar_evento_webhook(job_id):
    from api.models import WebhookEventoJob

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

    try:
        _procesar(job)
    except Exception:
        # Ningun error inesperado puede dejar el job en PROCESANDO indefinidamente (auditoria de
        # riesgos, hallazgo 3): si algo revienta aca que no sea OperationalError/InterfaceError
        # (esos SI reintentan via RETRY_DB, ver el decorador), el job queda RECHAZADO con la traza
        # en logs, nunca colgado sin que nadie pueda reintentarlo a mano.
        logger.exception(f'procesar_evento_webhook: fallo inesperado procesando job {job_id}')
        WebhookEventoJob.objects.filter(pk=job_id).update(
            estado=WebhookEventoJob.RECHAZADO,
            detalle='Error inesperado del servidor -- ver logs del worker.',
            finished_at=timezone.now(),
        )


def _procesar(job):
    from actions.models import Action
    from api.freno_demografico import verificar_freno, verificar_freno_volumen
    from api.models import MapeoResultadoCampana, WebhookEventoJob
    from lead.models import Lead

    payload = job.payload
    # Filtro SOLO por op primero, sin acotar por cartera en la query -- un ApiClient sin carteras
    # asignadas significa "todas" (ver ApiClient.tiene_acceso, mismo criterio que
    # ClienteCarteraScopedMixin en views.py). Un queryset vacio (client.carteras.all()) es falsy
    # en Python, asi que `... or None` lo convertia en None y `filter(x__in=None)` levantaba
    # TypeError no capturado -- exactamente la configuracion "sin carteras = todas" que el propio
    # diseño invita a usar. Bug real encontrado en la auditoria de riesgos, hallazgo 3.
    try:
        lead = Lead.objects.select_related('subcartera__cartera').get(op=payload['op'])
    except Lead.DoesNotExist:
        _rechazar(job, f'Lead con op={payload.get("op")!r} no encontrado.')
        return
    except Lead.MultipleObjectsReturned:
        # Lead.op no es unique globalmente -- si el mismo op existe en mas de una cartera, se
        # acota al alcance real del cliente antes de decidir si es ambiguo.
        candidatos = list(Lead.objects.select_related('subcartera__cartera').filter(op=payload['op']))
        candidatos = [l for l in candidatos if job.cliente.tiene_acceso(l.subcartera.cartera)]
        if len(candidatos) != 1:
            _rechazar(job, f'op={payload.get("op")!r} es ambiguo o está fuera del alcance de este cliente.')
            return
        lead = candidatos[0]

    cartera = lead.subcartera.cartera
    if not job.cliente.tiene_acceso(cartera):
        _rechazar(job, f'Lead con op={payload.get("op")!r} está fuera del alcance de cartera de este cliente.')
        return
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

    # Precaución obligatoria nº2 (plan de riesgos, Tanner): defensa en profundidad -- aunque
    # sembrar_mapeo_tanner.py ya verifica esto al crear el mapeo, se re-verifica aquí en cada
    # evento para que un MapeoResultadoCampana mal editado a mano (ej. desde /admin) nunca pueda
    # materializar un código bloqueado (129-153, PAC/venta directa) en un Action real.
    if cartera.arbol_tipo == 'tanner':
        from actions.arbol_templates import TANNER_CODIGOS_NO_MANUAL
        if mapeo.resultado.codigo in TANNER_CODIGOS_NO_MANUAL:
            _rechazar(job, f'Resultado {mapeo.resultado} tiene código bloqueado {mapeo.resultado.codigo!r} (TANNER_CODIGOS_NO_MANUAL).')
            return

    # Dos frenos independientes: demografico (cuenta efectos reales sobre Phone/email, requiere
    # que el Action lleve phone/email -- ver _resolver_contacto) y de volumen (cuenta CUALQUIER
    # evento aplicado, sin importar si toco demografia -- protege contra una descalibracion
    # masiva del motor externo aunque el resultado en cuestion no tenga efecto_demografia).
    freno_activo, motivo = verificar_freno(job.cliente, mapeo.resultado)
    if not freno_activo:
        freno_activo, motivo = verificar_freno_volumen(job.cliente)
    if freno_activo:
        job.estado = WebhookEventoJob.DETENIDO_FRENO
        job.detalle = f'Freno activo -- {motivo} Ver AccessLog y logs del worker.'
        job.finished_at = timezone.now()
        job.save(update_fields=['estado', 'detalle', 'finished_at'])
        return

    target = payload.get('target') or 'principal'
    phone, email = _resolver_contacto(lead, payload['canal'], target)

    # Atomico: si el guardado final del job fallara justo despues de crear el Action (auditoria
    # de riesgos, hallazgo 8), sin esto el Action quedaba huerfano -- contabilizado en el reporte
    # regulatorio de Tanner pero sin trazabilidad al event_id que lo origino, y un reintento de
    # Celery (RETRY_DB) encontraria el job todavia en PROCESANDO y no haria nada.
    with transaction.atomic():
        action = Action.objects.create(
            lead=lead, medio=mapeo.medio, resultado=mapeo.resultado, user=None,
            target=target, phone=phone, email=email,
            origen=Action.ORIGEN_SALIENTE, origen_masivo=True,
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
