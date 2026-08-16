import hashlib
import secrets

from django.db import models


class ApiClient(models.Model):
    """
    Credencial de un motor externo (ej. cobranza-saas) que consume la API de solo lectura de
    TurboTubo bajo /api/1.0/. Un ApiClient por integracion, no por usuario humano -- la
    autenticacion de la API es de maquina a maquina, separada del login de /dashboard/.

    La key nunca se guarda en texto plano (mismo criterio que un password): se muestra UNA vez
    al crearla (ver ApiClientAdmin) y de ahi en adelante solo se guarda su hash.
    """
    nombre = models.CharField(max_length=100, help_text='Ej. "cobranza-saas prod", "cobranza-saas staging".')
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    key_prefix = models.CharField(
        max_length=8, editable=False,
        help_text='Primeros caracteres de la key, solo para identificarla en el admin (no sirve para autenticar).',
    )
    activo = models.BooleanField(default=True)
    carteras = models.ManyToManyField(
        'cartera.Cartera', blank=True, related_name='api_clients',
        help_text='Carteras visibles para este cliente. Vacio = todas.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('nombre',)

    def __str__(self):
        return f'{self.nombre} ({self.key_prefix}…)'

    @staticmethod
    def hash_key(raw_key):
        return hashlib.sha256(raw_key.encode()).hexdigest()

    @classmethod
    def generar(cls, nombre, carteras=None):
        """Crea un ApiClient nuevo y devuelve (instancia, key_en_texto_plano). La key en texto
        plano NO se puede recuperar despues -- solo queda su hash."""
        raw_key = secrets.token_urlsafe(32)
        instancia = cls.objects.create(
            nombre=nombre, key_hash=cls.hash_key(raw_key), key_prefix=raw_key[:8],
        )
        if carteras:
            instancia.carteras.set(carteras)
        return instancia, raw_key

    def tiene_acceso(self, cartera):
        if not self.carteras.exists():
            return True
        return self.carteras.filter(pk=cartera.pk).exists()
