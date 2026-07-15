import logging
import re
from datetime import timedelta

from celery import shared_task
from django.core.files.base import ContentFile
from django.utils import timezone

from .models import PendingPbxCall, CallRecording
from .pbx_client import PbxClient, PbxError
from .pbx_matching import find_matching_cdr, cdr_id, parse_cdr_call_date, cdr_duration

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 20
MIN_AGE_SECONDS = 60  # give the call a minute to actually happen before we look for it
GIVE_UP_AFTER_HOURS = 24


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


@shared_task
def sync_pbx_recordings():
    cutoff_new_enough = timezone.now() - timedelta(seconds=MIN_AGE_SECONDS)
    give_up_before = timezone.now() - timedelta(hours=GIVE_UP_AFTER_HOURS)

    pending = (
        PendingPbxCall.objects
        .filter(resolved=False, requested_at__lte=cutoff_new_enough, attempts__lt=MAX_ATTEMPTS)
        .select_related('user__userprofile', 'lead', 'action__resultado')
    )

    by_user = {}
    for call in pending:
        by_user.setdefault(call.user_id, []).append(call)

    for user_id, calls in by_user.items():
        userprofile = calls[0].user.userprofile
        if not userprofile.has_pbx_credentials:
            continue

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
            continue

        client = PbxClient(userprofile.pbx_email, userprofile.pbx_password)
        month = timezone.now().strftime('%Y%m')

        for call in actionable:
            call.attempts += 1

            try:
                cdr_rows = client.list_cdr(month=month, destination=call.destination, since=call.requested_at)
            except PbxError as exc:
                logger.warning(f"sync_pbx_recordings: could not list CDR for user {user_id}: {exc}")
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
                        logger.warning(f"sync_pbx_recordings: could not download recording {call_id}: {exc}")
                        call.save(update_fields=['attempts'])
                        continue
                call.resolved = True
                call.resolved_at = timezone.now()
            elif call.requested_at < give_up_before:
                call.resolved = True
                call.resolved_at = timezone.now()

            call.save(update_fields=['attempts', 'resolved', 'resolved_at'])


@shared_task
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
