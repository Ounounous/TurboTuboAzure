import logging

from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)


class AccessLog(models.Model):
    """
    Registro liviano de accesos a datos de deudores (Ley 20.575, buena practica / apoyo al
    protocolo de brechas): quien consulto o extrajo datos, sobre que cliente y cuando. El "motivo"
    se infiere del tipo de accion (no se pide texto libre). Solo lo consulta admin, desde
    Configuracion -> Registros de acciones. Se purga segun RetentionSettings.dias_retencion_accesos.
    """
    VER_FICHA = 'ver_ficha'
    EXPORTAR_CLIENTES = 'exportar_clientes'
    EXPORTAR_TANNER = 'exportar_tanner'
    EXPORTAR_NUEVOCAPITAL = 'exportar_nuevocapital'
    EXPORTAR_COMPROMISOS = 'exportar_compromisos'
    EXPORTAR_GESTIONES = 'exportar_gestiones'
    DESCARGAR_GRABACIONES = 'descargar_grabaciones'

    CHOICES_ACCION = (
        (VER_FICHA, 'Vio ficha del cliente'),
        (EXPORTAR_CLIENTES, 'Exportó clientes'),
        (EXPORTAR_TANNER, 'Exportó reporte Tanner'),
        (EXPORTAR_NUEVOCAPITAL, 'Exportó reporte Nuevo Capital'),
        (EXPORTAR_COMPROMISOS, 'Exportó compromisos'),
        (EXPORTAR_GESTIONES, 'Exportó gestiones'),
        (DESCARGAR_GRABACIONES, 'Descargó grabaciones'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='accesos_registrados',
    )
    action_type = models.CharField(max_length=32, choices=CHOICES_ACCION)
    # Cliente accedido (si aplica). SET_NULL + snapshot del OP para que el registro sobreviva al
    # borrado del lead/cartera y siga sirviendo de evidencia de quien accedio a que.
    lead = models.ForeignKey('lead.Lead', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    lead_op = models.CharField(max_length=32, blank=True)
    detail = models.CharField(max_length=255, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [models.Index(fields=['-timestamp'])]

    def __str__(self):
        quien = self.user.username if self.user_id else 'sistema'
        return f'{quien} {self.get_action_type_display()} ({self.timestamp:%d-%m-%Y %H:%M})'


def registrar_acceso(user, action_type, lead=None, detail=''):
    """Deja constancia de un acceso. Nunca debe romper la request real: cualquier error se traga."""
    try:
        AccessLog.objects.create(
            user=user if getattr(user, 'is_authenticated', False) else None,
            action_type=action_type,
            lead=lead,
            lead_op=(lead.op if lead is not None else ''),
            detail=(detail or '')[:255],
        )
    except Exception as exc:  # noqa: BLE001 -- el registro de auditoria jamas debe tumbar el acceso
        logger.warning(f'registrar_acceso fallo ({action_type}): {exc}')
