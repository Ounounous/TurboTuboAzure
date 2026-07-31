"""
Unica fuente de verdad para retirar un PaymentCommitment (editarlo o marcarlo roto). No tocar
PaymentCommitment.vigente/motivo_retiro a mano por fuera de aca -- mismo espiritu que
lead/lifecycle.py para Lead.activo.
"""
from django.utils import timezone

from .models import Action, PaymentCommitment


def retirar_anteriores(lead, nuevo_commitment, user=None):
    """Un lead solo tiene UN compromiso vigente a la vez. Cualquier otro compromiso que le
    quedara vigente (de una gestion anterior, con o sin pasar por editar()) se retira como
    "editado" -- reemplazado por este. Se llama tanto desde editar() como desde Action.save()
    cuando una gestion normal (arbol de la cartera) genera un compromiso nuevo: sin esto, un lead
    con varias promesas hechas en distintas gestiones se quedaba con todas "vigentes" a la vez, y
    check_compromisos_rotos solo mira la mas nueva -- las viejas vencidas nunca se detectaban."""
    anteriores = PaymentCommitment.objects.filter(lead=lead, vigente=True).exclude(pk=nuevo_commitment.pk)
    anteriores.update(
        vigente=False, motivo_retiro=PaymentCommitment.MOTIVO_EDITADO,
        retirado_por=user, retirado_at=timezone.now(), reemplazado_por=nuevo_commitment,
    )


def editar(commitment, nueva_fecha, nuevo_monto, user, comentario=''):
    """Reemplaza un compromiso por uno nuevo (misma gestion, fecha/monto distintos). Reutiliza el
    MISMO medio/resultado/telefono/correo de la gestion que origino el compromiso (nunca se
    inventa un resultado nuevo): el resultado original ya crea compromiso, asi que con la fecha
    nueva compute_status vuelve a dejar el lead en Compromiso -- esto SI es una gestion real (un
    nuevo acuerdo con el cliente), asi que respeta el arbol de esa cartera como cualquier otra.
    El anterior queda retirado (vigente=False) SIN pasar por compromiso roto."""
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
    # Por si el lead tenia OTRO compromiso vigente ademas de este (de una gestion anterior que
    # nunca paso por aca) -- que no quede huerfano.
    retirar_anteriores(commitment.lead, nuevo_commitment, user=user)
    return nuevo_commitment


def marcar_roto(commitment, user, comentario=''):
    """Registra que el compromiso no se cumplio. Confirmado con el arbol de gestion de las 3
    carteras: NINGUNA pide reportar esto como una gestion, asi que a diferencia de editar() NO se
    crea un Action -- es puro cambio de status (compromiso roto = status Contactado), se guarda en
    su propia base: PaymentCommitment (vigente/motivo_retiro/comentario_retiro) mas
    StatusChangeLog via apply_status, igual que "Marcar al dia" de un supervisor
    (ver lead.views.MarcarAlDiaView)."""
    from .status_logic import apply_status
    from lead.models import Lead

    commitment.vigente = False
    commitment.motivo_retiro = PaymentCommitment.MOTIVO_ROTO
    commitment.retirado_por = user
    commitment.retirado_at = timezone.now()
    commitment.comentario_retiro = comentario
    commitment.save(update_fields=[
        'vigente', 'motivo_retiro', 'retirado_por', 'retirado_at', 'comentario_retiro',
    ])
    apply_status(commitment.lead, Lead.CONTACTADO, changed_by=user)
