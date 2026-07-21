from django.conf import settings
from django.db import models


class RetentionSettings(models.Model):
    """
    Configuracion global (una sola fila) de la purga de datos del ciclo de vida del lead. Guarda
    los plazos que consumen las tareas de purga: actions.tasks.purgar_gestiones_ciclo_vida (leads
    terminados/desasignados) y purge_status_change_log (historial de status). Editable en
    Configuracion -> Retencion de datos, o en /admin.
    """
    dias_purga_terminado = models.PositiveIntegerField(
        default=15,
        help_text='Dias despues del fin del mes en que se declaro "al dia" para purgar las '
                  'gestiones de un lead terminado (se conservan las grabaciones).',
    )
    dias_purga_desasignado = models.PositiveIntegerField(
        default=90,
        help_text='Dias desde que el lead quedo desasignado para purgar sus gestiones '
                  '(se conservan las grabaciones).',
    )
    dias_retencion_statuslog = models.PositiveIntegerField(
        default=90,
        help_text='Dias que se conserva el detalle del historial de cambios de status antes de '
                  'purgarlo (el "mejor status" es un campo del lead, no se pierde).',
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        verbose_name = 'Configuración de retención'
        verbose_name_plural = 'Configuración de retención'

    def __str__(self):
        return 'Configuración de retención'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
