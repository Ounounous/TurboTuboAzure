from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Cartera(models.Model):
    ARBOL_GALGO = 'galgo'
    ARBOL_TANNER = 'tanner'
    ARBOL_NUEVO_CAPITAL = 'nuevo_capital'
    CHOICES_ARBOL = (
        (ARBOL_GALGO, 'Galgo'),
        (ARBOL_TANNER, 'Tanner'),
        (ARBOL_NUEVO_CAPITAL, 'Nuevo Capital'),
    )

    nombre = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    activo = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='carteras_creadas'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Que plantilla de arbol de gestiones (medios/resultados) tiene esta cartera. Se asigna UNA
    # vez desde Carteras -> detalle (solo admin/owner) y, en esta version, no se puede volver
    # atras -- mezclar dos plantillas en la misma cartera dejaria el arbol en un estado ambiguo.
    # Una version futura permitira editar nodos sueltos sin reasignar todo.
    arbol_tipo = models.CharField(max_length=20, choices=CHOICES_ARBOL, blank=True)
    arbol_asignado_at = models.DateTimeField(null=True, blank=True)
    arbol_asignado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

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
    # Supervisores que pueden ver y gestionar ESTA subcartera (no toda la cartera). Una cartera
    # con varias subcarteras -- ej. una por supervisor, todas bajo el mismo nombre comercial
    # "Tanner" para que el reporte regulatorio (que busca la cartera por nombre) siga viendo todo
    # junto -- separa asi lo que ve cada supervisor sin tener que partir la cartera. M2M: una
    # subcartera puede tener 1 o varios supervisores. La asignacion la hace el admin (Django
    # admin o Configuracion -> Usuarios y permisos).
    supervisores = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name='subcarteras_supervisadas', blank=True,
    )
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
