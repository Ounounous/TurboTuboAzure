"""
Unica fuente de verdad para retirar un PaymentCommitment (editarlo o marcarlo roto). No tocar
PaymentCommitment.vigente/motivo_retiro a mano por fuera de aca -- mismo espiritu que
lead/lifecycle.py para Lead.activo.

Ambas operaciones reutilizan el MISMO medio/resultado/telefono/correo de la gestion que origino el
compromiso (nunca se inventa un resultado nuevo): asi la gestion nueva ya respeta el arbol de esa
cartera sin adivinar nada, y el motor de status (actions/status_logic.compute_status) hace el resto
solo con la fecha_compromiso que se le pasa.
"""
from django.utils import timezone

from .models import Action, PaymentCommitment


def editar(commitment, nueva_fecha, nuevo_monto, user, comentario=''):
    """Reemplaza un compromiso por uno nuevo (misma gestion, fecha/monto distintos). El resultado
    original ya crea compromiso -- con la fecha nueva, compute_status vuelve a dejar el lead en
    Compromiso. El anterior queda retirado (vigente=False) SIN pasar por compromiso roto."""
    original = commitment.action
    nueva_accion = Action.objects.create(
        lead=commitment.lead, medio=original.medio, resultado=original.resultado, user=user,
        phone=original.phone, email=original.email,
        fecha_compromiso=nueva_fecha, monto_compromiso=nuevo_monto,
        comment=comentario or f'Compromiso editado (reemplaza al del {commitment.fecha_compromiso:%d-%m-%Y}).',
    )
    nuevo_commitment = PaymentCommitment.objects.get(action=nueva_accion)

    commitment.vigente = False
    commitment.motivo_retiro = PaymentCommitment.MOTIVO_EDITADO
    commitment.retirado_por = user
    commitment.retirado_at = timezone.now()
    commitment.reemplazado_por = nuevo_commitment
    commitment.save(update_fields=[
        'vigente', 'motivo_retiro', 'retirado_por', 'retirado_at', 'reemplazado_por',
    ])
    return nuevo_commitment


def marcar_roto(commitment, user, comentario=''):
    """Registra que el compromiso no se cumplio: gestion nueva con el MISMO medio/resultado/dato
    de contacto que la origino, pero SIN fecha ni monto -- compute_status no encuentra fecha, asi
    que cae a "con contacto" y deja el lead en Contactado (no genera un compromiso nuevo)."""
    original = commitment.action
    Action.objects.create(
        lead=commitment.lead, medio=original.medio, resultado=original.resultado, user=user,
        phone=original.phone, email=original.email,
        comment=comentario or f'Compromiso roto (no se cumplio el del {commitment.fecha_compromiso:%d-%m-%Y}).',
    )

    commitment.vigente = False
    commitment.motivo_retiro = PaymentCommitment.MOTIVO_ROTO
    commitment.retirado_por = user
    commitment.retirado_at = timezone.now()
    commitment.save(update_fields=['vigente', 'motivo_retiro', 'retirado_por', 'retirado_at'])
