"""
Verificación de firma HMAC para el webhook de escritura (Contrato API v1, sección 1.2 "Evento").

Diseño (definido en el documento de riesgos de la integración, sección 04):
- La firma cubre event_id + timestamp + el cuerpo crudo, no solo el cuerpo. Sin el event_id en la
  firma, un atacante con acceso de red podría reenviar el mismo payload firmado bajo un event_id
  distinto y crear una segunda gestión -- la idempotencia por event_id (WebhookEventoJob.event_id)
  no alcanza a cubrir eso si la firma no ata ambos datos entre sí.
- Ventana de replay corta: un request con timestamp fuera de ventana se rechaza aunque la firma
  sea válida, incluso si es la primera vez que se ve ese event_id.
"""
import hashlib
import hmac
import time

# 2 min (antes 5): ventana mas ajustada, menos tiempo real para reenviar un request capturado
# (auditoria de riesgos, hallazgo 13). El motor emisor genera el timestamp en el momento de la
# request, asi que 2 min es margen de sobra para latencia de red real.
VENTANA_REPLAY_SEGUNDOS = 2 * 60
# Un timestamp Unix en segundos nunca tiene mas de 10-11 digitos hasta el año 5138. Sin este
# limite, un header X-Signature-Timestamp con miles de digitos pasa .isdigit() y fuerza a Python
# a construir un entero gigante en int(timestamp) antes de cualquier otra validacion -- un DoS
# de CPU barato (hallazgo 13), mas barato aun combinado con el bypass de throttle del hallazgo 4.
TIMESTAMP_MAX_DIGITOS = 12


class FirmaInvalida(Exception):
    pass


def firmar(secret: str, event_id: str, timestamp: str, cuerpo_crudo: bytes) -> str:
    mensaje = f'{event_id}.{timestamp}.'.encode() + cuerpo_crudo
    return hmac.new(secret.encode(), mensaje, hashlib.sha256).hexdigest()


def verificar(secret: str, event_id: str, timestamp: str, cuerpo_crudo: bytes, firma_recibida: str):
    """Levanta FirmaInvalida si la firma no calza o el timestamp está fuera de la ventana de
    replay. No devuelve nada -- el caller decide qué HTTP status usar."""
    if not timestamp or not timestamp.isdigit() or len(timestamp) > TIMESTAMP_MAX_DIGITOS:
        raise FirmaInvalida('Header X-Signature-Timestamp ausente o inválido.')

    ahora = int(time.time())
    ts = int(timestamp)
    if abs(ahora - ts) > VENTANA_REPLAY_SEGUNDOS:
        raise FirmaInvalida('Timestamp fuera de la ventana de replay permitida.')

    esperada = firmar(secret, event_id, timestamp, cuerpo_crudo)
    # compare_digest: comparación en tiempo constante, evita timing attack sobre la firma.
    if not hmac.compare_digest(esperada, firma_recibida or ''):
        raise FirmaInvalida('Firma HMAC inválida.')
