"""
Puntos de entrada que llaman actions.models (Action.save/Payment.save) y lead.lifecycle
(suspender/desasignar/reactivar/terminar) para dejar metadata anonimizada. Contrato: estas
funciones NUNCA deben poder romper la operacion real -- si algo falla aca (bug, dato
inesperado), se loggea y se sigue. Nunca se llaman desde dentro de un transaction.atomic() que
tambien contenga la escritura real (ver los call sites): un error de SQL aca no debe abortar la
transaccion de negocio.
"""
import logging

from django.utils import timezone

from .models import CicloVidaEvento, GestionEvento, PagoEvento, CHOICES_FRANJA
from .pseudonimos import cartera_token, cobrador_token, lead_token

logger = logging.getLogger(__name__)


def _franja(hora):
    if hora < 6:
        return CHOICES_FRANJA[0][0]
    if hora < 12:
        return CHOICES_FRANJA[1][0]
    if hora < 18:
        return CHOICES_FRANJA[2][0]
    return CHOICES_FRANJA[3][0]


def _dias_desde(fecha_inicio, momento):
    return (momento.date() - fecha_inicio.date()).days


def registrar_gestion(action, status_antes):
    try:
        _registrar_gestion(action, status_antes)
    except Exception:
        logger.exception('mlmetadata: fallo registrando gestion %s (no afecta la gestion real)', action.pk)


def _registrar_gestion(action, status_antes):
    from actions.models import Action

    lead = action.lead
    if not lead or not lead.subcartera_id:
        return
    momento = timezone.localtime(action.created_at)
    secuencia = Action.objects.filter(lead=lead, created_at__lte=action.created_at).count()
    dias_compromiso = (action.fecha_compromiso - momento.date()).days if action.fecha_compromiso else None

    GestionEvento.objects.create(
        lead_token=lead_token(lead),
        cartera_token=cartera_token(lead.subcartera.cartera),
        cobrador_token=cobrador_token(action.user),
        secuencia=secuencia,
        dias_desde_creacion_lead=_dias_desde(lead.created_at, momento),
        dia_semana=momento.weekday(),
        dia_del_mes=momento.day,
        franja_horaria=_franja(momento.hour),
        canal=action.medio.canal,
        es_llamada=action.medio.es_llamada,
        es_inbound=action.medio.es_inbound,
        target=action.target or '',
        contactabilidad=action.resultado.contactabilidad,
        tipo_contacto=action.resultado.tipo_contacto,
        crea_compromiso=action.resultado.crea_compromiso,
        requiere_fecha_pago=action.resultado.requiere_fecha_pago,
        efecto_pago=action.resultado.efecto_pago,
        dias_hasta_compromiso=dias_compromiso,
        status_antes=status_antes or '',
        status_despues=lead.status,
        ciclo_cartera=lead.ciclo_cartera,
        ciclo=lead.ciclo,
        tipo_cobranza=lead.tipo_cobranza,
        tiene_aval=lead.tiene_aval,
        saldo_insoluto=lead.saldo_insoluto,
        cuotas_atrasadas=lead.cuotas_atrasadas,
    )


def registrar_pago(payment, status_antes):
    try:
        _registrar_pago(payment, status_antes)
    except Exception:
        logger.exception('mlmetadata: fallo registrando pago %s (no afecta el pago real)', payment.pk)


def _registrar_pago(payment, status_antes):
    from actions.models import Action, PaymentCommitment

    lead = payment.lead
    if not lead or not lead.subcartera_id:
        return
    fecha = payment.fecha

    ultima_gestion = Action.objects.filter(
        lead=lead, created_at__date__lte=fecha
    ).order_by('-created_at').first()
    dias_ultima_gestion = (fecha - ultima_gestion.created_at.date()).days if ultima_gestion else None

    compromiso = PaymentCommitment.objects.filter(
        lead=lead, fecha_compromiso__lte=fecha
    ).order_by('-fecha_compromiso').first()
    dias_vs_compromiso = (fecha - compromiso.fecha_compromiso).days if compromiso else None

    PagoEvento.objects.create(
        lead_token=lead_token(lead),
        cartera_token=cartera_token(lead.subcartera.cartera),
        monto=payment.monto,
        tipo=payment.tipo,
        dia_semana=fecha.weekday(),
        dia_del_mes=fecha.day,
        dias_desde_ultima_gestion=dias_ultima_gestion,
        dias_vs_compromiso=dias_vs_compromiso,
        status_antes=status_antes or '',
        status_despues=lead.status,
    )


def registrar_transicion(lead, tipo):
    try:
        _registrar_transicion(lead, tipo)
    except Exception:
        logger.exception('mlmetadata: fallo registrando transicion %s de lead %s (no afecta la transicion real)', tipo, lead.pk)


def _registrar_transicion(lead, tipo):
    if not lead.subcartera_id:
        return
    CicloVidaEvento.objects.create(
        lead_token=lead_token(lead),
        cartera_token=cartera_token(lead.subcartera.cartera),
        tipo_transicion=tipo,
        dias_desde_creacion_lead=_dias_desde(lead.created_at, timezone.localtime()),
    )
