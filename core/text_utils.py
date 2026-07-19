import re
import unicodedata


def normalize_header(value):
    """'Fecha Compromiso' / 'fecha_compromiso' / 'FECHA-COMPROMISO' -> 'fecha_compromiso'."""
    value = str(value or '').strip().lower()
    value = ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '_', value).strip('_')
