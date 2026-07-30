from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class CargaMasiva(models.Model):
    """
    Un "lote": una subida de Excel (clientes, telefonos, gestiones, asignaciones, etc.) que se
    puede deshacer. Cada fila que la carga creo o modifico queda registrada en CargaMasivaCambio
    -- ver core/carga_tracking.py para como se usa esto desde cada vista de carga.
    """
    TIPO_CHOICES = (
        ('clientes', 'Clientes'),
        ('telefonos', 'Teléfonos'),
        ('email', 'Email'),
        ('direccion', 'Dirección'),
        ('bienes', 'Bienes'),
        ('aval', 'Aval'),
        ('asignaciones', 'Asignaciones'),
        ('gestiones', 'Gestiones'),
        ('suspensiones', 'Suspensiones (ciclo de vida)'),
    )

    COMPLETADA = 'completada'
    DESHECHA = 'deshecha'
    ESTADO_CHOICES = (
        (COMPLETADA, 'Completada'),
        (DESHECHA, 'Deshecha'),
    )

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='cargas_masivas',
    )
    archivo_nombre = models.CharField(max_length=255, blank=True)
    total_filas = models.PositiveIntegerField(default=0)
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default=COMPLETADA)
    created_at = models.DateTimeField(auto_now_add=True)
    deshecha_at = models.DateTimeField(null=True, blank=True)
    deshecha_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'Carga masiva'
        verbose_name_plural = 'Cargas masivas'

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.total_filas} fila(s) · {self.created_at:%d-%m-%Y %H:%M}"


class CargaMasivaCambio(models.Model):
    """
    Un cambio puntual (una fila) dentro de un lote. 'creado': deshacer = borrar el objeto.
    'actualizado': deshacer = devolver cada campo a su valor anterior (guardado en
    valores_anteriores como {"campo": [valor_anterior, valor_nuevo]}).

    Los objetos creados por una carga de CLIENTES (Lead) se borran en cascada por las FK
    normales del modelo (Action.lead=CASCADE, etc.) -- CallRecording.lead es SET_NULL, asi que
    las grabaciones sobreviven, igual que en cartera.services.eliminar_cartera. No hace falta
    logica especial para ese caso: Lead.objects.filter(pk=...).delete() ya se comporta asi.
    """
    ACCION_CREADO = 'creado'
    ACCION_ACTUALIZADO = 'actualizado'
    ACCION_CHOICES = (
        (ACCION_CREADO, 'Creado'),
        (ACCION_ACTUALIZADO, 'Actualizado'),
    )

    lote = models.ForeignKey(CargaMasiva, on_delete=models.CASCADE, related_name='cambios')
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    objeto = GenericForeignKey('content_type', 'object_id')
    accion = models.CharField(max_length=12, choices=ACCION_CHOICES)
    valores_anteriores = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('id',)
        indexes = [models.Index(fields=['content_type', 'object_id'])]
        verbose_name = 'Cambio de carga masiva'
        verbose_name_plural = 'Cambios de carga masiva'

    def __str__(self):
        return f"{self.get_accion_display()} · {self.content_type.model} #{self.object_id}"
