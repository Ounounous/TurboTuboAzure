import logging
import re
from datetime import timedelta

from celery import shared_task
from django.core.files.base import ContentFile
from django.db import InterfaceError, OperationalError
from django.utils import timezone

from .audio_compress import transcode_to_opus
from .models import PendingPbxCall, CallRecording
from .pbx_client import PbxClient, PbxError, get_pbx_master_client
from .pbx_matching import find_matching_cdr, cdr_id, parse_cdr_call_date, cdr_duration

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 20
MIN_AGE_SECONDS = 60  # give the call a minute to actually happen before we look for it
GIVE_UP_AFTER_HOURS = 24
# Tras esta cantidad de intentos SIN conseguir el audio (list_cdr falla, el CDR nunca aparece, o
# aparece pero la descarga falla), se deja de reintentar y se crea un CallRecording sin archivo
# (ver _crear_placeholder) para que el supervisor sepa buscarla a mano en pbxip.cl. Los intentos
# se espacian por tiempo REAL (PLACEHOLDER_RETRY_SPACING_MINUTES, via last_attempt_at), no por
# cuantas veces corrio el cron -- con 3 intentos separados 20 min, el plazo total antes de
# rendirse es ~40-60 min. Si en produccion pbxip.cl tarda mas que eso en publicar el CDR (mas
# placeholders "sin match" de los esperados), subir cualquiera de las dos constantes, no toca
# nada mas.
PLACEHOLDER_MAX_ATTEMPTS = 3
PLACEHOLDER_RETRY_SPACING_MINUTES = 20

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


def build_recording_filename(action, ext='mp3'):
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
    return '_'.join(parts) + f'.{ext}'


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


@shared_task(rate_limit='30/m', **RETRY_DB)
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
    # Modo maestro: una sola cuenta admin consulta el API y el usuario solo necesita su extension
    # (con ella se cruza el CDR). Si no hay cuenta maestra configurada, se cae al modo por-usuario
    # (cada uno con sus credenciales completas), como antes.
    master = get_pbx_master_client()
    if master is not None:
        if not userprofile.pbx_extension:
            logger.warning(
                f"sync_pbx_recordings_user: el usuario {userprofile.user.username} hizo llamadas "
                f"pero no tiene EXTENSION SIP guardada -- no se pueden cruzar sus grabaciones."
            )
            return 0
    elif not userprofile.has_pbx_credentials:
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

    # La cuenta maestra (si esta) hace la consulta; si no, las credenciales del propio usuario.
    client = master if master is not None else PbxClient(userprofile.pbx_email, userprofile.pbx_password)
    month = timezone.now().strftime('%Y%m')
    resueltas = 0

    retry_spacing = timedelta(minutes=PLACEHOLDER_RETRY_SPACING_MINUTES)

    for call in actionable:
        # Espaciado real: si ya se consulto esta llamada hace menos de 20 min, se salta este
        # ciclo del cron entero -- "3 intentos" tiene que significar 3 intentos de verdad
        # separados en el tiempo, no 3 pasadas del cron (que puede correr cada pocos minutos).
        if call.last_attempt_at and timezone.now() - call.last_attempt_at < retry_spacing:
            continue

        call.attempts += 1
        call.last_attempt_at = timezone.now()
        dar_por_vencido = call.attempts >= PLACEHOLDER_MAX_ATTEMPTS or call.requested_at < give_up_before

        try:
            cdr_rows = client.list_cdr(month=month, destination=call.destination, since=call.requested_at)
        except PbxError as exc:
            logger.warning(f"sync_pbx_recordings_user: could not list CDR for user {user_id}: {exc}")
            if dar_por_vencido:
                _crear_placeholder(call, CallRecording.SIN_AUDIO_ERROR_API, detalle=str(exc))
                call.resolved = True
                call.resolved_at = timezone.now()
            call.save(update_fields=['attempts', 'last_attempt_at', 'resolved', 'resolved_at'])
            continue

        match = find_matching_cdr(
            cdr_rows, call.destination, call.requested_at, extension=userprofile.pbx_extension,
        )

        if match:
            call_id = cdr_id(match)
            if not CallRecording.objects.filter(cdr_id=call_id, month=month).exists():
                try:
                    audio_bytes = client.download_recording(month, call_id)
                    audio_bytes, ext = transcode_to_opus(audio_bytes)
                    filename = build_recording_filename(call.action, ext=ext)
                    recording = CallRecording(
                        pending_call=call, lead=call.lead, action=call.action, user=call.user,
                        cdr_id=call_id, month=month, destination=call.destination,
                        call_date=parse_cdr_call_date(match), duration_seconds=cdr_duration(match),
                    )
                    recording.audio_file.save(filename, ContentFile(audio_bytes), save=True)
                except PbxError as exc:
                    logger.warning(f"sync_pbx_recordings_user: could not download recording {call_id}: {exc}")
                    if dar_por_vencido:
                        # Se encontro el CDR (sabemos el cdr_id exacto) pero la descarga del
                        # audio fallo las veces que se reintento: se deja el placeholder CON el
                        # cdr_id, para que el supervisor lo busque directo por ese id en pbxip.cl.
                        _crear_placeholder(
                            call, CallRecording.SIN_AUDIO_DESCARGA_FALLIDA, detalle=str(exc),
                            cdr_id_val=call_id, month=month,
                            call_date=parse_cdr_call_date(match), duration_seconds=cdr_duration(match),
                        )
                        call.resolved = True
                        call.resolved_at = timezone.now()
                    call.save(update_fields=['attempts', 'last_attempt_at', 'resolved', 'resolved_at'])
                    continue
            call.resolved = True
            call.resolved_at = timezone.now()
            resueltas += 1
        elif dar_por_vencido:
            # Nunca aparecio un CDR que calzara con esta llamada (ni tras los reintentos, ni
            # dentro del plazo maximo de espera): se avisa igual, sin cdr_id, para que el
            # supervisor sepa que la llamada existio y la busque a mano por destino/fecha.
            _crear_placeholder(call, CallRecording.SIN_AUDIO_SIN_MATCH, month=month)
            call.resolved = True
            call.resolved_at = timezone.now()

        call.save(update_fields=['attempts', 'last_attempt_at', 'resolved', 'resolved_at'])

    return resueltas


def _crear_placeholder(call, motivo, detalle='', cdr_id_val=None, month='', call_date=None, duration_seconds=None):
    """Deja un CallRecording SIN audio_file cuando no se pudo conseguir el audio ni tras los
    reintentos -- para que la llamada quede visible en el listado en vez de desaparecer en
    silencio, con el motivo y (si se llego a encontrar) el cdr_id exacto para buscarla a mano."""
    if CallRecording.objects.filter(pending_call=call).exists():
        return  # ya se dejo un placeholder (o una grabacion real) para esta llamada
    recording = CallRecording(
        pending_call=call, lead=call.lead, action=call.action, user=call.user,
        cdr_id=cdr_id_val, month=month, destination=call.destination,
        call_date=call_date, duration_seconds=duration_seconds,
        sin_audio_motivo=motivo, sin_audio_detalle=detalle[:2000],
    )
    recording.save()


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
        # Solo vigentes: uno editado ya tiene un reemplazo con fecha propia; uno marcado roto a
        # mano (ver actions/commitment_lifecycle.py) ya saco al lead de status=compromiso, asi
        # que ni siquiera entraria al filtro de abajo -- pero se excluye igual por prolijidad.
        PaymentCommitment.objects.filter(lead=OuterRef('pk'), vigente=True)
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
    AUTORECUPERACION. Recalcula los campos DERIVADOS que pudieron quedar desincronizados si un
    save fallo a medias, una tarea no corrio, o una carga no recomputo: (1) inubicable segun la
    demografia actual, y (2) el acople al dia -> terminado. Es idempotente: en un sistema sano no
    cambia nada, asi que puede correr cada noche sin costo ni ruido, y sana solo cualquier deriva.

    Antes recorria TODOS los leads uno por uno, con una query de "tiene contacto activo" POR
    LEAD -- a escala (100k+ leads) es un full-scan nocturno con una query por fila. Ahora:
      - Primero se acota a los leads que REALMENTE pueden necesitar el cambio (mismo filtro que
        ya aplicaba recompute_inubicable puertas adentro: al_dia+activo para el acople, y
        recien_asignado/no_contactado/inubicable para lo demografico) -- el resto de la tabla ni
        se toca, ni se consulta.
      - Dentro de esos candidatos, "tiene contacto activo" se calcula en UNA query por chunk de
        500 (no una por lead), y solo se escribe (UPDATE + StatusChangeLog) lo que efectivamente
        cambia de estado -- se compara antes de guardar, nunca se pisa lo que ya estaba bien.
    """
    from django.db.models import Exists, OuterRef, Q
    from demographics.models import Phone, IDDemographics, AvalDemographics, Email, CONTACT_ACTIVE
    from lead.models import Lead, StatusChangeLog
    from lead.lifecycle import terminar

    revisados, corregidos = 0, 0

    # 1) Acople al dia -> terminado que pudo perderse: filtro directo (suele ser un puñado de
    #    filas), no hace falta pasar por el resto de la logica de abajo.
    for lead in Lead.objects.filter(status=Lead.AL_DIA, activo=Lead.ACTIVO).iterator(chunk_size=CHUNK):
        terminar(lead)
        corregidos += 1

    # 2) Inubicable segun demografia: candidatos = mismos 3 status que ya filtraba
    #    recompute_inubicable adentro (recien_asignado/no_contactado/inubicable). INUBICABLE y
    #    NO_CONTACTADO son los 2 rangos mas bajos de Lead.STATUS_RANK (0 y 1): moverse entre
    #    ellos nunca sube status_historico, asi que aca no hace falta tocarlo (recompute_inubicable
    #    tampoco lo hubiera subido en estos 2 casos -- ver apply_status).
    candidatos_ids = list(
        Lead.objects.filter(status__in=[Lead.RECIEN_ASIGNADO, Lead.NO_CONTACTADO, Lead.INUBICABLE])
        .values_list('pk', flat=True).iterator(chunk_size=CHUNK)
    )
    revisados = len(candidatos_ids)

    for i in range(0, len(candidatos_ids), CHUNK):
        chunk_ids = candidatos_ids[i:i + CHUNK]

        # Una sola query para TODO el chunk: que leads de este chunk tienen algun dato de
        # contacto activo (mismo criterio que _tiene_contacto_activo, aplicado en bloque).
        con_contacto = set(
            Lead.objects.filter(pk__in=chunk_ids).annotate(
                _tel=Exists(Phone.objects.filter(lead=OuterRef('pk'), phone_number_status=CONTACT_ACTIVE)),
                _mail=Exists(IDDemographics.objects.filter(
                    lead=OuterRef('pk'), principal_email_status=CONTACT_ACTIVE).exclude(principal_email='')),
                _mail2=Exists(Email.objects.filter(lead=OuterRef('pk'), email_status=CONTACT_ACTIVE)),
                _aval=Exists(AvalDemographics.objects.filter(
                    id_demographics__lead=OuterRef('pk'), aval_email_status=CONTACT_ACTIVE,
                ).exclude(aval_email='').exclude(aval_email__isnull=True)),
            ).filter(Q(_tel=True) | Q(_mail=True) | Q(_mail2=True) | Q(_aval=True))
            .values_list('pk', flat=True)
        )
        status_actual = dict(Lead.objects.filter(pk__in=chunk_ids).values_list('pk', 'status'))

        a_marcar_inubicable = [
            pk for pk in chunk_ids
            if pk not in con_contacto and status_actual[pk] in (Lead.RECIEN_ASIGNADO, Lead.NO_CONTACTADO)
        ]
        a_desmarcar = [
            pk for pk in chunk_ids
            if pk in con_contacto and status_actual[pk] == Lead.INUBICABLE
        ]

        if a_marcar_inubicable:
            Lead.objects.filter(pk__in=a_marcar_inubicable).update(status=Lead.INUBICABLE)
            StatusChangeLog.objects.bulk_create(
                StatusChangeLog(lead_id=pk, new_status=Lead.INUBICABLE) for pk in a_marcar_inubicable
            )
            corregidos += len(a_marcar_inubicable)
        if a_desmarcar:
            Lead.objects.filter(pk__in=a_desmarcar).update(status=Lead.NO_CONTACTADO)
            StatusChangeLog.objects.bulk_create(
                StatusChangeLog(lead_id=pk, new_status=Lead.NO_CONTACTADO) for pk in a_desmarcar
            )
            corregidos += len(a_desmarcar)

    logger.info(f"reconciliar_estados: {revisados} candidato(s) revisado(s), {corregidos} corregido(s)")
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


@shared_task(**RETRY_DB)
def purgar_access_log(dias=None):
    """
    Purga el registro de accesos a datos de deudores (configuracion.AccessLog, Ley 20.575) mas
    viejo que `dias`. El plazo sale de RetentionSettings.dias_retencion_accesos (editable en
    Configuracion -> Retencion de datos). El propio registro es dato personal, asi que no se
    conserva indefinidamente.
    """
    from configuracion.models import AccessLog

    if dias is None:
        try:
            from suspensiones.models import RetentionSettings
            dias = RetentionSettings.get_solo().dias_retencion_accesos
        except Exception:
            dias = 90
    corte = timezone.now() - timedelta(days=dias)
    borrados, _ = AccessLog.objects.filter(timestamp__lt=corte).delete()
    logger.info(f"purgar_access_log: {borrados} registro(s) de acceso mas viejos que {dias} dias eliminados")
    return borrados


@shared_task(**RETRY_DB)
def purgar_asignaciones(dias=None):
    """
    Acota el crecimiento de LeadAssignment (una fila por cada (re)asignacion de un lead a un
    cobrador): borra las mas viejas que `dias`. La asignacion ACTUAL vive en Lead.assigned_to, no
    aca, asi que purgar el rastro historico no pierde a quien esta asignado cada lead hoy. El plazo
    sale de RetentionSettings.dias_retencion_asignaciones (editable en Configuracion -> Retencion).
    """
    from lead.models import LeadAssignment

    if dias is None:
        try:
            from suspensiones.models import RetentionSettings
            dias = RetentionSettings.get_solo().dias_retencion_asignaciones
        except Exception:
            dias = 180
    corte = timezone.now() - timedelta(days=dias)
    borrados, _ = LeadAssignment.objects.filter(assigned_at__lt=corte).delete()
    logger.info(f"purgar_asignaciones: {borrados} asignacion(es) mas viejas que {dias} dias eliminadas")
    return borrados


@shared_task(**RETRY_DB)
def purgar_compromisos_rotos(dias=None):
    """
    Borra los PaymentCommitment marcados como rotos (motivo_retiro='roto') mas viejos que `dias`
    dias desde que se retiraron (retirado_at). El plazo sale de
    RetentionSettings.dias_retencion_compromisos_rotos (editable en Configuracion -> Retencion de
    datos, default ~2 meses). No toca los vigentes ni los editados -- solo el rastro historico de
    promesas incumplidas, que ya cumplio su proposito (el status del lead ya quedo actualizado via
    apply_status al momento de marcarlo roto, ver actions/commitment_lifecycle.py).
    """
    from .models import PaymentCommitment

    if dias is None:
        try:
            from suspensiones.models import RetentionSettings
            dias = RetentionSettings.get_solo().dias_retencion_compromisos_rotos
        except Exception:
            dias = 60
    corte = timezone.now() - timedelta(days=dias)
    borrados, _ = PaymentCommitment.objects.filter(
        motivo_retiro=PaymentCommitment.MOTIVO_ROTO, retirado_at__lt=corte,
    ).delete()
    logger.info(f"purgar_compromisos_rotos: {borrados} compromiso(s) roto(s) mas viejos que {dias} dias eliminados")
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
    'actions.tasks.purgar_access_log': 8,
    'actions.tasks.purgar_asignaciones': 8,
    'actions.tasks.purgar_compromisos_rotos': 8,
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


@shared_task(**RETRY_DB)
def generar_zip_grabaciones(job_id):
    """
    Arma el ZIP de grabaciones de un GrabacionesExportJob en el WORKER (no en la web). Lee el Excel
    que subio el usuario, junta las grabaciones visibles para el, y guarda el ZIP en el propio job.
    Cualquier fallo deja el job en estado ERROR con el detalle, nunca revienta en silencio.
    """
    from django.core.files.base import ContentFile
    from actions.exports import construir_zip_grabaciones
    from actions.models import GrabacionesExportJob

    try:
        job = GrabacionesExportJob.objects.get(pk=job_id)
    except GrabacionesExportJob.DoesNotExist:
        logger.warning(f"generar_zip_grabaciones: job {job_id} no existe (¿se borró?)")
        return

    job.estado = GrabacionesExportJob.PROCESANDO
    job.save(update_fields=['estado'])

    try:
        with job.excel.open('rb') as excel_fileobj:
            spool, total, errores = construir_zip_grabaciones(excel_fileobj, job.solicitado_por)

        job.total = total
        job.errores = '\n'.join(errores)
        if total == 0:
            job.estado = GrabacionesExportJob.VACIO
        else:
            spool.seek(0)
            job.archivo.save(f'grabaciones_{job.pk}.zip', ContentFile(spool.read()), save=False)
            job.estado = GrabacionesExportJob.LISTO
        spool.close()
    except Exception:
        logger.exception(f"generar_zip_grabaciones: falló el job {job_id}")
        job.estado = GrabacionesExportJob.ERROR
        job.errores = 'Ocurrió un error generando el ZIP. Reintenta o avisa a soporte.'

    job.finished_at = timezone.now()
    job.save(update_fields=['estado', 'total', 'errores', 'archivo', 'finished_at'])
