"""
Motor de status del lead: el status deja de editarse a mano (salvo "Al dia" por un supervisor,
ver lead.views.MarcarAlDiaView) y se calcula solo a partir de las gestiones (Action) y los pagos
(Payment) reales. Las reglas fueron validadas fila por fila sobre los arboles de gestion de
Galgo, Tanner y Nuevo Capital.
"""
from lead.models import Lead, StatusChangeLog


def compute_status(resultado, fecha_compromiso):
    """Status que corresponde al lead segun el resultado de una gestion recien guardada."""
    from .models import Resultado

    if resultado.efecto_pago == Resultado.EFECTO_AL_DIA:
        return Lead.AL_DIA
    if resultado.efecto_pago == Resultado.EFECTO_PAGANDO:
        return Lead.PAGANDO
    if resultado.crea_compromiso and fecha_compromiso:
        return Lead.COMPROMISO
    if resultado.contactabilidad == Resultado.CON_CONTACTO:
        return Lead.CONTACTADO
    return Lead.NO_CONTACTADO


def apply_status(lead, new_status, changed_by=None):
    """Actualiza status actual + historico (si new_status es mejor) y deja registro en el log."""
    lead.status = new_status
    if Lead.STATUS_RANK[new_status] > Lead.STATUS_RANK.get(lead.status_historico, 0):
        lead.status_historico = new_status
    lead.save(update_fields=['status', 'status_historico'])
    StatusChangeLog.objects.create(lead=lead, changed_by=changed_by, new_status=new_status)
