import logging
import re
from datetime import timedelta

from celery import shared_task
from django.core.files.base import ContentFile
from django.db import InterfaceError, OperationalError
from django.utils import timezone

from .models import PendingPbxCall, CallRecording
from .pbx_client import PbxClient, PbxError
from .pbx_matching import find_matching_cdr, cdr_id, parse_cdr_call_date, cdr_duration

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 20
MIN_AGE_SECONDS = 60  # give the call a minute to actually happen before we look for it
GIVE_UP_AFTER_HOURS = 24

# Reintentos con backoff exponencial ante errores transitorios de BD (conexion caida/reinicio).
# Junto con CONN_HEALTH_CHECKS en settings, una tarea no muere por un hipo de la base: reintenta.
RETRY_DB = dict(
    autoretry_for=(OperationalError, InterfaceError),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)

# Batch para las tareas que recorren todos los leads (evita cargar todo en memoria / una sola
# transaccion gigante).
CHUNK = 500

# Piso legal de retencion de gestiones de cobranza. La Ley 21.320 (art. 37 de la Ley 19.496)
# obliga a "registrar, almacenar y mantener disponible el tipo y frecuencia de las gestiones que
# realicen por cada deudor por un plazo de AL MENOS DOS ANIOS, contado desde su realizacion".
# Es un minimo legal, NO una preferencia: aunque Retencion de datos configure un plazo menor,
# ninguna gestion se purga antes de 2 anios. Como Zona Sur es la "empresa de cobranza" del art.
# 37, aplica de lleno.
RETENCION_GESTIONES_DIAS = 730


def _safe_part(value):
    value = str(value or '').strip()
    value = re.sub(r'[\\/:*?"<>|]', '', value)
    value = re.sub(r'\s+', '_', value)
    return value or '-'


def build_recording_filename(action):
    lead = action.lead
    fecha = timezone.localtime(action.created_at).strftime('%d-%m-%Y_%H%M')
    parts = [
        _safe_part(lead.op),
        _safe_part(action.resultado.nombre),
        fecha,
        _safe_part(lead.subcartera.cartera.nombre),
        _safe_part(lead.subcartera.nombre),
        _safe_part(action.user.username if action.user else ''),
    ]
    return '_'.join(parts) + '.mp3'


@shared_task(**RETRY_DB)
def sync_pbx_recordings():
    """
    Reparte el trabajo: despacha UNA subtarea por usuario con llamadas pendientes, para que se
    procesen en paralelo y una central lenta (o caida) no bloquee a los demas colectores.
    """
    cutoff_new_enough = timezone.now() - timedelta(seconds=MIN_AGE_SECONDS)
    user_ids = list(
        PendingPbxCall.objects
        .filter(resolved=False, requested_at__lte=cutoff_new_enough, attempts__lt=MAX_ATTEMPTS)
        # order_by('user_id') limpia el Meta.ordering ('-requested_at'), que si no rompe el
        # distinct() (Django lo agrega al SELECT y deja de deduplicar) -> usuario repetido.
        .order_by('user_id').values_list('user_id', flat=True).distinct()
    )
    for uid in user_ids:
        sync_pbx_recordings_user.delay(uid)
    return user_ids


@shared_task(**RETRY_DB)
def sync_pbx_recordings_user(user_id):
    """Procesa las grabaciones pendientes de UN usuario (aislado del resto)."""
    cutoff_new_enough = timezone.now() - timedelta(seconds=MIN_AGE_SECONDS)
    give_up_before = timezone.now() - timedelta(hours=GIVE_UP_AFTER_HOURS)

    calls = list(
        PendingPbxCall.objects
        .filter(user_id=user_id, resolved=False, requested_at__lte=cutoff_new_enough, attempts__lt=MAX_ATTEMPTS)
        .select_related('user__userprofile', 'lead', 'action__resultado')
    )
    if not calls:
        return 0

    userprofile = calls[0].user.userprofile
    if not userprofile.has_pbx_credentials:
        return 0

    # Solo nos molestamos en consultar la central si hay al menos una llamada
    # cuya gestion ya fue guardada y realmente requiere grabacion.
    actionable = [c for c in calls if c.action_id and c.action.resultado.descarga_grabacion]
    not_yet_actioned = [c for c in calls if not c.action_id]

    # Las gestiones ya resueltas SIN grabacion requerida se cierran sin llamar al API.
    for call in calls:
        if call.action_id and not call.action.resultado.descarga_grabacion:
            call.resolved = True
            call.resolved_at = timezone.now()
            call.save(update_fields=['resolved', 'resolved_at'])

    for call in not_yet_actioned:
        call.attempts += 1
        if call.requested_at < give_up_before:
            call.resolved = True
            call.resolved_at = timezone.now()
        call.save(update_fields=['attempts', 'resolved', 'resolved_at'])

    if not actionable:
        return 0

    client = PbxClient(userprofile.pbx_email, userprofile.pbx_password)
    month = timezone.now().strftime('%Y%m')
    resueltas = 0

    for call in actionable:
        call.attempts += 1

        try:
            cdr_rows = client.list_cdr(month=month, destination=call.destination, since=call.requested_at)
        except PbxError as exc:
            logger.warning(f"sync_pbx_recordings_user: could not list CDR for user {user_id}: {exc}")
            call.save(update_fields=['attempts'])
            continue

        match = find_matching_cdr(
            cdr_rows, call.destination, call.requested_at, extension=userprofile.pbx_extension,
        )

        if match:
            call_id = cdr_id(match)
            if not CallRecording.objects.filter(cdr_id=call_id, month=month).exists():
                try:
                    audio_bytes = client.download_recording(month, call_id)
                    filename = build_recording_filename(call.action)
                    recording = CallRecording(
                        pending_call=call, lead=call.lead, action=call.action, user=call.user,
                        cdr_id=call_id, month=month, destination=call.destination,
                        call_date=parse_cdr_call_date(match), duration_seconds=cdr_duration(match),
                    )
                    recording.audio_file.save(filename, ContentFile(audio_bytes), save=True)
                except PbxError as exc:
                    logger.warning(f"sync_pbx_recordings_user: could not download recording {call_id}: {exc}")
                    call.save(update_fields=['attempts'])
                    continue
            call.resolved = True
            call.resolved_at = timezone.now()
            resueltas += 1
        elif call.requested_at < give_up_before:
            call.resolved = True
            call.resolved_at = timezone.now()

        call.save(update_fields=['attempts', 'resolved', 'resolved_at'])

    return resueltas


@shared_task(**RETRY_DB)
def purge_expired_recordings():
    """Ley: borra grabaciones que superaron su retencion (2 anios desde la llamada)."""
    today = timezone.now().date()
    expired = CallRecording.objects.filter(retention_until__lt=today)
    count = expired.count()
    for recording in expired:
        recording.audio_file.delete(save=False)
    expired.delete()
    logger.info(f"purge_expired_recordings: {count} grabacion(es) vencida(s) eliminada(s)")
    return count


@shared_task(**RETRY_DB)
def reset_status_mensual():
    """
    Corre el dia 1 de cada mes: el status actual de todo lead gestionable (activo) vuelve a
    "no contactado" (el historico -- el mejor status que alguna vez tuvo -- no se toca).
    "Inubicable" queda afuera: es derivado de la demografia y la reconciliacion nocturna lo
    volveria a marcar igual. Se hace con UN solo UPDATE masivo (no fila por fila) y SIN escribir
    un StatusChangeLog por lead: el reseteo mensual es un evento de sistema, no auditoria por
    cliente, y evitar N filas/mes es clave para el tamano del log.
    """
    from lead.models import Lead

    updated = (
        Lead.objects.filter(activo=Lead.ACTIVO)
        .exclude(status__in=[Lead.INUBICABLE, Lead.NO_CONTACTADO])
        .update(status=Lead.NO_CONTACTADO)
    )
    logger.info(f"reset_status_mensual: {updated} lead(s) reseteado(s) a no contactado")
    return updated


@shared_task(**RETRY_DB)
def check_compromisos_rotos():
    """
    Corre a diario: un lead en status "compromiso" cuyo ULTIMO PaymentCommitment vencio hace 1
    dia o mas pasa a "compromiso roto". Se resuelve con una consulta (subquery de la ultima fecha)
    + un UPDATE masivo + un bulk_create de logs -- constante en numero de queries, no fila por fila.
    No hace falta revisar pagos ni compromisos nuevos: si hubiera pasado algo, Payment.save()/
    Action.save() ya habrian sacado al lead de "compromiso" antes de que corra esta tarea.
    """
    from django.db.models import OuterRef, Subquery
    from lead.models import Lead, StatusChangeLog
    from .models import PaymentCommitment

    hoy = timezone.now().date()
    ultimo_compromiso = (
        PaymentCommitment.objects.filter(lead=OuterRef('pk'))
        .order_by('-fecha_compromiso').values('fecha_compromiso')[:1]
    )
    pks = list(
        Lead.objects.filter(status=Lead.COMPROMISO, activo=Lead.ACTIVO)
        .annotate(ultima_fecha=Subquery(ultimo_compromiso))
        .filter(ultima_fecha__lte=hoy - timedelta(days=1))
        .values_list('pk', flat=True)
    )
    if pks:
        Lead.objects.filter(pk__in=pks).update(status=Lead.COMPROMISO_ROTO)
        StatusChangeLog.objects.bulk_create(
            [StatusChangeLog(lead_id=pk, new_status=Lead.COMPROMISO_ROTO) for pk in pks]
        )
    logger.info(f"check_compromisos_rotos: {len(pks)} lead(s) pasado(s) a compromiso roto")
    return len(pks)


@shared_task(**RETRY_DB)
def reconciliar_estados():
    """
    AUTORECUPERACION. Recorre todos los leads (por lotes) y recalcula los campos DERIVADOS que
    pudieron quedar desincronizados si un save fallo a medias, una tarea no corrio, o una carga
    no recomputo: (1) inubicable segun la demografia actual, y (2) el acople al dia -> terminado.
    Es idempotente: en un sistema sano no cambia nada (recompute solo escribe si algo difiere),
    asi que puede correr cada noche sin costo ni ruido, y sana solo cualquier deriva.
    """
    from lead.models import Lead
    from lead.lifecycle import terminar
    from .status_logic import recompute_inubicable

    revisados, corregidos = 0, 0
    for lead in Lead.objects.all().iterator(chunk_size=CHUNK):
        antes = (lead.status, lead.status_historico, lead.activo)
        # Acople al dia -> terminado que pudo perderse.
        if lead.status == Lead.AL_DIA and lead.activo == Lead.ACTIVO:
            terminar(lead)
        # Inubicable segun la demografia actual (solo mueve no_contactado/recien_asignado).
        recompute_inubicable(lead)
        revisados += 1
        if (lead.status, lead.status_historico, lead.activo) != antes:
            corregidos += 1
    logger.info(f"reconciliar_estados: {revisados} revisado(s), {corregidos} corregido(s)")
    return corregidos


@shared_task(**RETRY_DB)
def purgar_gestiones_ciclo_vida():
    """
    FASE 2 de retencion (Ley 21.719): purga los datos accesorios -- gestiones (Action, que en
    cascada se lleva sus compromisos de pago) y notas internas (LeadNote, texto libre) -- de los
    leads cuya finalidad de tratamiento ya ceso: TERMINADOS (deuda pagada) y DESASIGNADOS. Los
    plazos son configurables en Configuracion -> Retencion de datos:
      - terminado:    N dias despues del FIN DEL MES en que se declaro "al dia".
      - desasignado:  N dias desde que quedo desasignado.

    Se CONSERVAN a proposito: el lead en si (dato de credito con base legal: RUT, nombre, deuda),
    los pagos (respaldo contable), y las grabaciones (retencion legal propia de 2 anios, ver
    purge_expired_recordings). La demografia (telefonos/correos adquiridos) NO se toca todavia:
    depende de la marca de procedencia (dato del credito vs adquirido) que es fase 3.

    PISO LEGAL (Ley 21.320, art. 37): las gestiones de cobranza deben conservarse >= 2 anios desde
    su realizacion, aunque la config ponga un plazo menor. Como un lead terminado/desasignado ya no
    recibe gestiones nuevas (no es gestionable), basta exigir 2 anios desde el evento del ciclo de
    vida para garantizar que TODA gestion suya supere los 2 anios; ademas se filtra por created_at
    al borrar, como resguardo explicito. Las notas internas (LeadNote) NO son gestiones de cobranza
    -- son recordatorios del equipo, no contacto con el deudor -- asi que no les aplica el piso.

    Idempotente y acotada: solo mira leads con datos_purgados_at nulo, y lo setea al purgar.
    """
    import calendar
    from lead.models import Lead, LeadNote
    from .models import Action

    cfg = _retention_settings()
    hoy = timezone.now().date()
    # Piso legal (Ley 21.320): ninguna gestion se purga antes de 2 anios desde su realizacion.
    corte_gestiones = hoy - timedelta(days=RETENCION_GESTIONES_DIAS)

    def _fin_de_mes(d):
        return d.replace(day=calendar.monthrange(d.year, d.month)[1])

    # Terminados: elegibles cuando fin_de_mes(terminado_at) + plazo <= hoy Y ademas ya pasaron 2
    # anios desde terminado_at (piso legal: sus gestiones -- todas <= terminado_at -- superan los
    # 2 anios). Se filtra en Python porque el "fin de mes" varia por fila.
    terminados = [
        lead.pk
        for lead in Lead.objects.filter(
            activo=Lead.TERMINADO, terminado_at__isnull=False, datos_purgados_at__isnull=True
        ).only('pk', 'terminado_at').iterator(chunk_size=CHUNK)
        if _fin_de_mes(lead.terminado_at) + timedelta(days=cfg.dias_purga_terminado) <= hoy
        and lead.terminado_at <= corte_gestiones
    ]

    # Desasignados: plazo fijo desde desasignado_at. El plazo efectivo es el mayor entre el
    # configurado y el piso legal de 2 anios, para no purgar gestiones de < 2 anios.
    plazo_desasignado = max(cfg.dias_purga_desasignado, RETENCION_GESTIONES_DIAS)
    corte_desasignado = hoy - timedelta(days=plazo_desasignado)
    desasignados = list(
        Lead.objects.filter(
            activo=Lead.DESASIGNADO, desasignado_at__isnull=False,
            desasignado_at__lte=corte_desasignado, datos_purgados_at__isnull=True,
        ).values_list('pk', flat=True)
    )

    pks = terminados + desasignados
    if not pks:
        logger.info('purgar_gestiones_ciclo_vida: nada que purgar.')
        return 0

    for i in range(0, len(pks), CHUNK):
        chunk = pks[i:i + CHUNK]
        # Borrar Action arrastra su PaymentCommitment (OneToOne CASCADE) y deja CallRecording y
        # PendingPbxCall con action=NULL (SET_NULL): la grabacion sobrevive. El filtro por
        # created_at es el resguardo explicito del piso legal de 2 anios (Ley 21.320): en la
        # practica la elegibilidad ya lo garantiza, pero asi ninguna gestion reciente se pierde.
        Action.objects.filter(lead_id__in=chunk, created_at__date__lte=corte_gestiones).delete()
        LeadNote.objects.filter(lead_id__in=chunk).delete()
        Lead.objects.filter(pk__in=chunk).update(datos_purgados_at=hoy)

    logger.info(
        f'purgar_gestiones_ciclo_vida: {len(pks)} lead(s) purgado(s) '
        f'({len(terminados)} terminado(s), {len(desasignados)} desasignado(s)).'
    )
    return len(pks)


def _retention_settings():
    from suspensiones.models import RetentionSettings
    return RetentionSettings.get_solo()


@shared_task(**RETRY_DB)
def purge_status_change_log(dias=None):
    """
    Acota el crecimiento de StatusChangeLog: borra registros mas viejos que `dias`. El historico
    "mejor status" NO vive aca (es un campo del lead), asi que purgar el log no pierde
    informacion de negocio, solo el detalle antiguo.

    El plazo se puede fijar por parametro (para pruebas), y si no, sale de
    RetentionSettings.dias_retencion_statuslog (editable en Configuracion -> Retencion de
    datos), con STATUSLOG_RETENTION_DAYS de settings como ultimo fallback.
    """
    from django.conf import settings
    from lead.models import StatusChangeLog

    if dias is None:
        try:
            from suspensiones.models import RetentionSettings
            dias = RetentionSettings.get_solo().dias_retencion_statuslog
        except Exception:
            dias = getattr(settings, 'STATUSLOG_RETENTION_DAYS', 90)
    corte = timezone.now() - timedelta(days=dias)
    borrados, _ = StatusChangeLog.objects.filter(timestamp__lt=corte).delete()
    logger.info(f"purge_status_change_log: {borrados} registro(s) mas viejos que {dias} dias eliminados")
    return borrados


# Ventana maxima (en dias) que puede pasar sin que cada tarea programada corra, antes de avisar.
HEARTBEAT_MAX_DIAS = {
    'actions.tasks.reset_status_mensual': 32,
    'actions.tasks.check_compromisos_rotos': 2,
    'actions.tasks.reconciliar_estados': 2,
    'actions.tasks.purge_expired_recordings': 8,
    # sync_pbx_recordings corre cada pocos minutos en produccion (resuelve llamadas pendientes
    # dentro de su ventana de 24h, ver GIVE_UP_AFTER_HOURS) -- si se detiene un dia entero, las
    # grabaciones dejan de bajarse.
    'actions.tasks.sync_pbx_recordings': 1,
    'actions.tasks.purge_status_change_log': 8,
    'actions.tasks.purgar_gestiones_ciclo_vida': 2,
    'mlmetadata.tasks.exportar_metadata_ml': 8,
}


@shared_task(**RETRY_DB)
def verificar_tareas_programadas():
    """
    AUTORECUPERACION (deteccion): revisa que las tareas criticas realmente esten programadas y
    hayan corrido dentro de su ventana. Si una no esta configurada en Celery Beat o quedo atrasada,
    lo deja en el log como WARNING (para alertar), en vez de que falle en silencio.
    """
    try:
        from django_celery_beat.models import PeriodicTask
    except ImportError:
        logger.warning('verificar_tareas_programadas: django_celery_beat no disponible.')
        return []

    ahora = timezone.now()
    problemas = []
    for task_name, max_dias in HEARTBEAT_MAX_DIAS.items():
        pt = PeriodicTask.objects.filter(task=task_name, enabled=True).first()
        if not pt:
            problemas.append(f'{task_name}: NO programada (o deshabilitada) en Celery Beat.')
            continue
        if pt.last_run_at is None:
            problemas.append(f'{task_name}: programada pero nunca corrio.')
        elif (ahora - pt.last_run_at) > timedelta(days=max_dias):
            problemas.append(f'{task_name}: sin correr hace mas de {max_dias} dias (ultima: {pt.last_run_at:%Y-%m-%d}).')

    for p in problemas:
        logger.warning(f'verificar_tareas_programadas: {p}')
    if not problemas:
        logger.info('verificar_tareas_programadas: todas las tareas criticas al dia.')
    return problemas
