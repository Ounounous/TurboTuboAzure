"""
Helpers to match a PendingPbxCall against a CDR entry returned by pbxip.cl.

Field names confirmed against zoiper_bot_mudo, a sibling project already talking
to this same API in production (the public OpenAPI spec doesn't document the
CDR row schema): id, calldate, duration, destination, direction, src_extension,
attended ("1"/"0" string, not boolean).
"""
import re


def _last_digits(value, n=8):
    digits = re.sub(r'\D', '', str(value or ''))
    return digits[-n:] if digits else ''


def cdr_destination(cdr_row):
    return cdr_row.get('destination') or cdr_row.get('dst') or ''


def cdr_id(cdr_row):
    return str(cdr_row.get('id') or cdr_row.get('uniqueid') or cdr_row.get('uuid') or '')


def cdr_call_date(cdr_row):
    return cdr_row.get('calldate') or cdr_row.get('date') or None


def parse_cdr_call_date(cdr_row):
    """Same as cdr_call_date but returns a timezone-aware datetime (or None).

    pbxip.cl returns `calldate` already in UTC (confirmed empirically: it lines up
    to within a couple seconds of our own UTC `requested_at` timestamps) -- NOT in
    the PBX's local Chile time. Treat naive values as UTC, not Django's local TZ.
    """
    from django.utils.dateparse import parse_datetime
    from django.utils import timezone
    import datetime as dt

    raw_date = cdr_call_date(cdr_row)
    if not raw_date:
        return None
    call_dt = parse_datetime(str(raw_date))
    if not call_dt:
        return None
    if timezone.is_naive(call_dt):
        call_dt = timezone.make_aware(call_dt, dt.timezone.utc)
    return call_dt


def cdr_duration(cdr_row):
    return cdr_row.get('duration') or cdr_row.get('billsec') or None


def cdr_answered(cdr_row):
    """True if the call was actually picked up ("attended" comes back as "1"/"0")."""
    return str(cdr_row.get('attended', '0')) == '1'


def find_matching_cdr(cdr_rows, destination, requested_at, extension=None, window_minutes=180):
    """
    Best-effort match: same trailing digits (+ same src_extension if given),
    outgoing, calldate on/after requested_at within window. Prefers the earliest
    matching call after requested_at.
    """
    target_digits = _last_digits(destination)
    best = None
    for row in cdr_rows:
        if _last_digits(cdr_destination(row)) != target_digits:
            continue
        if row.get('direction') and row.get('direction') != 'outgoing':
            continue
        if extension and str(row.get('src_extension', '')) != str(extension):
            continue
        if not cdr_answered(row):
            continue
        call_dt = parse_cdr_call_date(row)
        if not call_dt:
            continue
        delta_seconds = (call_dt - requested_at).total_seconds()
        if -60 <= delta_seconds <= window_minutes * 60:
            if best is None or call_dt < best[1]:
                best = (row, call_dt)
    return best[0] if best else None
