"""
Transiciones del ciclo de vida del lead (campo Lead.activo): suspender / desasignar / terminar /
reactivar. Centraliza el seteo de las fechas asociadas para que la purga de datos (fase 2) tenga
siempre un punto de referencia confiable. No editar Lead.activo a mano por fuera de aca.
"""
from django.utils import timezone


def suspender(lead, motivo='', changed_by=None):
    """El lead deja de gestionarse (orden judicial o del cliente). Conserva su asignado."""
    from .models import Lead
    lead.activo = Lead.SUSPENDIDO
    lead.suspendido_at = timezone.localdate()
    lead.motivo_suspension = (motivo or '').strip()
    lead.save(update_fields=['activo', 'suspendido_at', 'motivo_suspension'])
    _registrar_metadata(lead, 'suspendido')


def desasignar(lead, changed_by=None):
    """Saca el lead del pool activo y le quita el usuario asignado."""
    from .models import Lead
    lead.activo = Lead.DESASIGNADO
    lead.desasignado_at = timezone.localdate()
    lead.assigned_to = None
    lead.save(update_fields=['activo', 'desasignado_at', 'assigned_to'])
    _registrar_metadata(lead, 'desasignado')


def terminar(lead, changed_by=None):
    """El lead pago toda su deuda. Se dispara solo desde apply_status al llegar a 'al dia'."""
    from .models import Lead
    lead.activo = Lead.TERMINADO
    lead.terminado_at = timezone.localdate()
    lead.save(update_fields=['activo', 'terminado_at'])
    _registrar_metadata(lead, 'terminado')


def reactivar(lead, changed_by=None):
    """Vuelve el lead a 'activo' y limpia las marcas del estado anterior."""
    from .models import Lead
    lead.activo = Lead.ACTIVO
    lead.suspendido_at = None
    lead.desasignado_at = None
    lead.terminado_at = None
    # Se vuelve a gestionar: si sus datos ya se habian purgado por retencion, limpiar la marca
    # para que una futura terminacion/desasignacion lo haga elegible de nuevo.
    lead.datos_purgados_at = None
    lead.motivo_suspension = ''
    lead.save(update_fields=[
        'activo', 'suspendido_at', 'desasignado_at', 'terminado_at', 'datos_purgados_at',
        'motivo_suspension',
    ])
    _registrar_metadata(lead, 'reactivado')


def _registrar_metadata(lead, tipo):
    """Metadata anonimizada para entrenar/recomendar acciones de cobranza (mlmetadata). No hay
    transaction.atomic() aca arriba que proteger, pero igual nunca debe poder tumbar la
    transicion real -- registrar_transicion ya se traga cualquier excepcion."""
    from mlmetadata.capture import registrar_transicion
    registrar_transicion(lead, tipo)
