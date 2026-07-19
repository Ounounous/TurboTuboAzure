from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Cartera(models.Model):
    nombre = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    activo = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='carteras_creadas'
    )
    # Supervisores que pueden ver y gestionar esta cartera. M2M: una cartera puede tener 1 o
    # varios. Un supervisor solo ve las carteras donde esta aca (admin/owner ven todas). La
    # asignacion la hace el admin (Django admin hoy, dashboard de configuracion despues).
    supervisores = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name='carteras_supervisadas', blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('nombre',)

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nombre)
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            Subcartera.objects.create(cartera=self, nombre=self.nombre, es_default=True)

    @property
    def subcartera_default(self):
        return self.subcarteras.filter(es_default=True).first()


class Subcartera(models.Model):
    cartera = models.ForeignKey(Cartera, on_delete=models.CASCADE, related_name='subcarteras')
    nombre = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, blank=True)
    es_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('nombre',)
        unique_together = ('cartera', 'nombre')

    def __str__(self):
        return f"{self.cartera.nombre} / {self.nombre}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nombre)
        super().save(*args, **kwargs)
