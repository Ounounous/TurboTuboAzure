"""
Metadata anonimizada del ciclo de vida de los leads y sus gestiones, para entrenar/evaluar
recomendaciones de accion de cobranza. Ver mlmetadata/capture.py para como se llena y
mlmetadata/tasks.py para como se exporta.

Regla dura: estos modelos NUNCA guardan nombre, RUT, telefono, correo, direccion, texto libre
(comentarios/motivos) ni el nombre real de la cartera. Los identificadores (lead/cartera/
cobrador) son tokens locales sin relacion reversible fuera de las tablas de pseudonimo de esta
misma app -- ver mlmetadata/pseudonimos.py.
"""
import uuid

from django.conf import settings
from django.db import models


class CarteraPseudonimo(models.Model):
    """Mapeo cartera real -> token opaco. Vive SOLO en esta base -- nunca se exporta esta tabla,
    solo el token ya resuelto queda en los eventos."""
    cartera = models.OneToOneField('cartera.Cartera', on_delete=models.CASCADE, related_name='pseudonimo_ml')
    token = models.CharField(max_length=32, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.token


class LeadPseudonimo(models.Model):
    lead = models.OneToOneField('lead.Lead', on_delete=models.CASCADE, related_name='pseudonimo_ml')
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.token)


class CobradorPseudonimo(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pseudonimo_ml')
    token = models.CharField(max_length=32, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.token


FRANJA_MADRUGADA = 'madrugada'
FRANJA_MANANA = 'manana'
FRANJA_TARDE = 'tarde'
FRANJA_NOCHE = 'noche'

CHOICES_FRANJA = [
    (FRANJA_MADRUGADA, 'Madrugada (0-6h)'),
    (FRANJA_MANANA, 'Mañana (6-12h)'),
    (FRANJA_TARDE, 'Tarde (12-18h)'),
    (FRANJA_NOCHE, 'Noche (18-24h)'),
]


class EventoBase(models.Model):
    """Campos comunes a todo evento anonimizado: a que lead/cartera pertenece (por token, no por
    FK -- ver el comentario en lead_token) y si ya salio en un export."""
    lead_token = models.UUIDField(db_index=True)
    cartera_token = models.CharField(max_length=32, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    exportado_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        abstract = True


class GestionEvento(EventoBase):
    """Un evento (estado, accion, resultado) por cada gestion (Action) real. Es la unidad de
    entrenamiento principal: que se hizo, cuando (de forma relativa/bucketizada, nunca fecha
    calendario exacta), y que efecto tuvo sobre el status del lead."""
    cobrador_token = models.CharField(max_length=32, null=True, blank=True, db_index=True)

    secuencia = models.PositiveIntegerField(help_text='N-esima gestion de este lead (1 = la primera).')
    dias_desde_creacion_lead = models.IntegerField()
    dia_semana = models.PositiveSmallIntegerField(help_text='0=lunes .. 6=domingo')
    dia_del_mes = models.PositiveSmallIntegerField()
    franja_horaria = models.CharField(max_length=10, choices=CHOICES_FRANJA)

    canal = models.CharField(max_length=10)
    es_llamada = models.BooleanField()
    es_inbound = models.BooleanField()
    target = models.CharField(max_length=10, blank=True)

    contactabilidad = models.CharField(max_length=15, blank=True)
    tipo_contacto = models.CharField(max_length=50, blank=True)
    crea_compromiso = models.BooleanField()
    requiere_fecha_pago = models.BooleanField()
    efecto_pago = models.CharField(max_length=10, blank=True)
    dias_hasta_compromiso = models.IntegerField(null=True, blank=True)

    status_antes = models.CharField(max_length=20)
    status_despues = models.CharField(max_length=20)

    ciclo_cartera = models.CharField(max_length=20)
    ciclo = models.CharField(max_length=20)
    tipo_cobranza = models.CharField(max_length=20)
    tiene_aval = models.CharField(max_length=2)
    saldo_insoluto = models.IntegerField()
    cuotas_atrasadas = models.IntegerField()

    class Meta:
        ordering = ['-created_at']


class PagoEvento(EventoBase):
    """Un pago real. El desenlace (reward) que casi todo el resto de la metadata intenta
    predecir/optimizar."""
    monto = models.PositiveIntegerField()
    tipo = models.CharField(max_length=10)
    dia_semana = models.PositiveSmallIntegerField()
    dia_del_mes = models.PositiveSmallIntegerField()
    dias_desde_ultima_gestion = models.IntegerField(null=True, blank=True)
    dias_vs_compromiso = models.IntegerField(
        null=True, blank=True,
        help_text='Negativo = pago antes del compromiso, positivo = despues, null = sin compromiso previo.',
    )
    status_antes = models.CharField(max_length=20, blank=True)
    status_despues = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ['-created_at']


TRANSICION_SUSPENDIDO = 'suspendido'
TRANSICION_DESASIGNADO = 'desasignado'
TRANSICION_REACTIVADO = 'reactivado'
TRANSICION_TERMINADO = 'terminado'

CHOICES_TRANSICION = [
    (TRANSICION_SUSPENDIDO, 'Suspendido'),
    (TRANSICION_DESASIGNADO, 'Desasignado'),
    (TRANSICION_REACTIVADO, 'Reactivado'),
    (TRANSICION_TERMINADO, 'Terminado'),
]


class CicloVidaEvento(EventoBase):
    """Transiciones del ciclo de vida operativo del lead (distinto del status de cobranza): que
    deja de trabajarse, por que via, y cuando. Sin el motivo (texto libre)."""
    tipo_transicion = models.CharField(max_length=15, choices=CHOICES_TRANSICION)
    dias_desde_creacion_lead = models.IntegerField()

    class Meta:
        ordering = ['-created_at']
