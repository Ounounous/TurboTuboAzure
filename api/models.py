import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _hmac_fernet():
    # Mismo mecanismo que Userprofile.pbx_password (userprofile/models.py) -- Fernet simetrico,
    # PBX_ENCRYPTION_KEY ya existe en el entorno. A diferencia de la API key (que solo se compara
    # por hash), el secreto HMAC lo necesita el motor externo en texto plano para firmar cada
    # request, asi que no puede guardarse solo hasheado -- se cifra en vez de hashear.
    if not settings.PBX_ENCRYPTION_KEY:
        raise ValueError('PBX_ENCRYPTION_KEY no está configurado en el entorno.')
    return Fernet(settings.PBX_ENCRYPTION_KEY.encode())


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
    # Secreto para firmar webhooks de escritura (POST /api/1.0/webhooks/eventos/, Fase 4 del
    # Contrato API v1). Vacio hasta que el cliente lo necesite -- un ApiClient de solo lectura
    # (Fase 2/3) no tiene por que tener uno.
    hmac_secret_encrypted = models.CharField(max_length=500, blank=True)

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

    @property
    def hmac_secret(self):
        if not self.hmac_secret_encrypted:
            return ''
        try:
            return _hmac_fernet().decrypt(self.hmac_secret_encrypted.encode()).decode()
        except InvalidToken:
            return ''

    def generar_hmac_secret(self):
        """Genera y guarda un secreto HMAC nuevo; devuelve el valor en texto plano (se muestra
        una sola vez al admin, igual que la API key)."""
        raw = secrets.token_urlsafe(32)
        self.hmac_secret_encrypted = _hmac_fernet().encrypt(raw.encode()).decode()
        self.save(update_fields=['hmac_secret_encrypted'])
        return raw


class MapeoResultadoCampana(models.Model):
    """
    Tabla de mapeo del vocabulario corto de campaña (Contrato API v1, sección 2: entregado,
    no_entregado, sin_whatsapp, humano_detectado, buzon_detectado, sin_respuesta, error_conexion,
    no_disponible) al Resultado real de cada cartera (sección 3 del contrato). Configurable, no
    hardcodeada: cartera nueva = filas nuevas aquí, no un release del motor externo.
    """
    CANALES = [
        ('sms', 'SMS'), ('email', 'Email'), ('whatsapp', 'WhatsApp'),
        ('carta', 'Carta'), ('ivr', 'IVR'),
    ]
    RESULTADOS_CORTOS = [
        ('entregado', 'Entregado'), ('no_entregado', 'No entregado'),
        ('sin_whatsapp', 'Sin WhatsApp'), ('humano_detectado', 'Humano detectado'),
        ('buzon_detectado', 'Buzón detectado'), ('sin_respuesta', 'Sin respuesta'),
        ('error_conexion', 'Error de conexión'), ('no_disponible', 'No disponible'),
    ]

    cartera = models.ForeignKey('cartera.Cartera', on_delete=models.CASCADE, related_name='mapeos_campana')
    canal = models.CharField(max_length=10, choices=CANALES)
    resultado_corto = models.CharField(max_length=20, choices=RESULTADOS_CORTOS)
    medio = models.ForeignKey('actions.Medio', on_delete=models.PROTECT, related_name='+')
    resultado = models.ForeignKey('actions.Resultado', on_delete=models.PROTECT, related_name='+')

    class Meta:
        unique_together = ('cartera', 'canal', 'resultado_corto')
        verbose_name = 'Mapeo resultado campaña'
        verbose_name_plural = 'Mapeos resultado campaña'

    def __str__(self):
        return f'{self.cartera.nombre} / {self.canal} / {self.resultado_corto} → {self.resultado.nombre}'


class WebhookEventoJob(models.Model):
    """
    Un evento del webhook de escritura (POST /api/1.0/webhooks/eventos/, Contrato API v1 sección
    1.2). El receptor solo valida firma + idempotencia y responde 202; este job es lo que el
    worker procesa (crea el Action) -- nunca en el proceso web (ver plan de riesgos, "carga sobre
    producción": Action.save() dispara compromiso + status + efecto demográfico + captura ML).
    """
    PENDIENTE = 'pendiente'
    PROCESANDO = 'procesando'
    APLICADO = 'aplicado'
    RECHAZADO = 'rechazado'
    DETENIDO_FRENO = 'detenido_freno'
    CHOICES_ESTADO = [
        (PENDIENTE, 'En cola'),
        (PROCESANDO, 'Procesando'),
        (APLICADO, 'Aplicado'),
        (RECHAZADO, 'Rechazado'),
        (DETENIDO_FRENO, 'Detenido por freno de efectos demográficos'),
    ]

    # Clave de idempotencia del contrato -- un event_id repetido nunca crea un segundo Action.
    event_id = models.CharField(max_length=64, unique=True)
    cliente = models.ForeignKey(ApiClient, on_delete=models.PROTECT, related_name='webhook_eventos')
    payload = models.JSONField()
    estado = models.CharField(max_length=16, choices=CHOICES_ESTADO, default=PENDIENTE)
    action = models.ForeignKey(
        'actions.Action', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    detalle = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Evento de webhook'
        verbose_name_plural = 'Eventos de webhook'

    def __str__(self):
        return f'{self.event_id} ({self.estado})'
