"""
Verificación de firma HMAC para el webhook de escritura (Contrato API v1, sección 1.2 "Evento").

Diseño (definido en el documento de riesgos de la integración, sección 04):
- La firma cubre event_id + timestamp + el cuerpo crudo, no solo el cuerpo. Sin el event_id en la
  firma, un atacante con acceso de red podría reenviar el mismo payload firmado bajo un event_id
  distinto y crear una segunda gestión -- la idempotencia por event_id (WebhookEventoJob.event_id)
  no alcanza a cubrir eso si la firma no ata ambos datos entre sí.
- Ventana de replay ~5 min: un request con timestamp fuera de ventana se rechaza aunque la firma
  sea válida, incluso si es la primera vez que se ve ese event_id.
"""
import hashlib
import hmac
import time

VENTANA_REPLAY_SEGUNDOS = 5 * 60


class FirmaInvalida(Exception):
    pass


def firmar(secret: str, event_id: str, timestamp: str, cuerpo_crudo: bytes) -> str:
    mensaje = f'{event_id}.{timestamp}.'.encode() + cuerpo_crudo
    return hmac.new(secret.encode(), mensaje, hashlib.sha256).hexdigest()


def verificar(secret: str, event_id: str, timestamp: str, cuerpo_crudo: bytes, firma_recibida: str):
    """Levanta FirmaInvalida si la firma no calza o el timestamp está fuera de la ventana de
    replay. No devuelve nada -- el caller decide qué HTTP status usar."""
    if not timestamp or not timestamp.isdigit():
        raise FirmaInvalida('Header X-Signature-Timestamp ausente o inválido.')

    ahora = int(time.time())
    ts = int(timestamp)
    if abs(ahora - ts) > VENTANA_REPLAY_SEGUNDOS:
        raise FirmaInvalida('Timestamp fuera de la ventana de replay permitida (~5 min).')

    esperada = firmar(secret, event_id, timestamp, cuerpo_crudo)
    # compare_digest: comparación en tiempo constante, evita timing attack sobre la firma.
    if not hmac.compare_digest(esperada, firma_recibida or ''):
        raise FirmaInvalida('Firma HMAC inválida.')
