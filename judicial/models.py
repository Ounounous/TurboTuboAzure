from django.conf import settings
from django.db import models


class JudicialSettings(models.Model):
    """
    Configuración global (una sola fila) de la sección "API e info judicial". Por ahora solo
    controla si el estado judicial de los leads se muestra en el resto del sistema (ficha del
    cliente); el dato en sí (Lead.estado_judicial) se sigue cargando aunque esté apagado.
    """
    mostrar_info_judicial = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        verbose_name = 'Configuración judicial'
        verbose_name_plural = 'Configuración judicial'

    def __str__(self):
        return 'Configuración judicial'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
