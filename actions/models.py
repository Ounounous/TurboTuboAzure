from datetime import timedelta

from django.core.validators import FileExtensionValidator
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from lead.models import Lead
from team.models import Team
from cartera.models import Cartera
from demographics.models import Phone, IDItem, IDDemographics, AvalDemographics


class Medio(models.Model):
    CANAL_TELEFONO = 'telefono'
    CANAL_EMAIL = 'email'

    CHOICES_CANAL = [
        (CANAL_TELEFONO, _('Teléfono')),
        (CANAL_EMAIL, _('Email')),
    ]

    cartera = models.ForeignKey(Cartera, on_delete=models.CASCADE, related_name='medios')
    nombre = models.CharField(max_length=50)
    canal = models.CharField(max_length=10, choices=CHOICES_CANAL)
    # Distinto de "canal": WhatsApp y SMS tambien usan un numero de telefono (canal=telefono)
    # pero no son llamadas de voz por la central -- solo un medio con es_llamada=True puede
    # tener una grabacion real en pbxip.cl.
    es_llamada = models.BooleanField(default=False)
    # Codigo numerico que exige el reporte de la cartera (ej. Tanner: 1=Manual, 6=Email...).
    # Vacio para carteras cuyo reporte usa el nombre en vez de un codigo (ej. Galgo).
    codigo = models.CharField(max_length=20, blank=True)
    # Gestion entrante (el cliente nos contacto): ej. Nuevo Capital distingue "LLAMADA RECIBIDA",
    # "WHATSAPP RECIBIDO", etc. Su reporte deriva el "Origen Gestion" de esto (In=1 / Out=2).
    es_inbound = models.BooleanField(default=False)
    # Si el gestor puede usar este medio en el formulario manual de gestion. Los medios masivos
    # (IVR, SMS, discador, bot, correo/whatsapp/llamada RECIBIDOS) no se gestionan uno por uno:
    # se cargan por Excel. Solo la llamada directa manual, WhatsApp y correo saliente quedan en True.
    permite_manual = models.BooleanField(default=True)

    # Nombres del medio de "llamada directa manual" segun cada cartera. En el formulario manual
    # todos se muestran con la etiqueta unica "Llamar".
    NOMBRES_LLAMADA_MANUAL = {'MANUAL', 'LLAMADA', 'LLAMADO', 'TELEFONICO', 'TELEFÓNICO'}

    class Meta:
        ordering = ('nombre',)
        unique_together = ('cartera', 'nombre')

    def __str__(self):
        return f"{self.cartera.nombre} / {self.nombre}"

    @property
    def es_llamada_manual(self):
        """La llamada directa que hace el gestor a mano (se muestra como botón 'Llamar')."""
        return (
            self.canal == Medio.CANAL_TELEFONO
            and not self.es_inbound
            and self.nombre.strip().upper() in Medio.NOMBRES_LLAMADA_MANUAL
        )

    @property
    def es_whatsapp(self):
        return 'WHATSAPP' in self.nombre.strip().upper()

    def calcular_permite_manual(self):
        """Regla de negocio: qué medios aparecen en el formulario manual de gestión."""
        if self.es_inbound:
            return False
        if self.canal == Medio.CANAL_EMAIL:
            return True  # correo saliente se gestiona manual
        nombre = self.nombre.strip().upper()
        if 'WHATSAPP' in nombre:
            return True
        return nombre in Medio.NOMBRES_LLAMADA_MANUAL


class Resultado(models.Model):
    CON_CONTACTO = 'con_contacto'
    SIN_CONTACTO = 'sin_contacto'

    CHOICES_CONTACTABILIDAD = [
        (CON_CONTACTO, _('Con contacto')),
        (SIN_CONTACTO, _('Sin contacto')),
    ]

    EFECTO_PAGANDO = 'pagando'
    EFECTO_AL_DIA = 'al_dia'

    CHOICES_EFECTO_PAGO = [
        ('', _('No aplica')),
        (EFECTO_PAGANDO, _('Pagando')),
        (EFECTO_AL_DIA, _('Al día')),
    ]

    # Resultado pertenece directo a la Cartera, no a un Medio: en la practica (confirmado con
    # Tanner) el resultado de una gestion es independiente de por que medio se logro -- "Promesa
    # de pago" puede darse por llamada manual, discador, whatsapp o bot por igual. Medio y
    # Resultado se eligen por separado en el formulario.
    cartera = models.ForeignKey(Cartera, on_delete=models.CASCADE, related_name='resultados')
    nombre = models.CharField(max_length=255)
    # Codigo numerico que exige el reporte de la cartera (ej. Tanner COD 100-800). Vacio si la
    # cartera no usa codigos (ej. Galgo, que reporta por nombre).
    codigo = models.CharField(max_length=20, blank=True)
    # Clasificacion mas fina que "contactabilidad" (ej. Tanner: DIRECTO, DIRECTO AVAL, INDIRECTO,
    # SIN CONTACTO OPERADOR, SIN CONTACTO MAQUINA, SIN CONTACTO TERRENO, ACCION MASIVA, SIN
    # GESTION). Se completa sola al elegir el resultado, no se muestra como campo aparte.
    tipo_contacto = models.CharField(max_length=50, blank=True)
    contactabilidad = models.CharField(max_length=15, choices=CHOICES_CONTACTABILIDAD, blank=True)
    es_default = models.BooleanField(default=False)
    crea_compromiso = models.BooleanField(default=False)
    requiere_fecha_pago = models.BooleanField(
        default=False,
        help_text=_('Si está activo, la gestión exige una fecha de compromiso/pago asociada.')
    )
    # Efecto de este resultado sobre el status del lead, mas alla de contacto/compromiso: por
    # ahora solo Galgo tiene resultados de pago real dentro del arbol de gestion (PAGO / AL DIA,
    # PAGO / CONTENIDO); Tanner y Nuevo Capital no reportan pagos por gestion (ver Payment.save()).
    efecto_pago = models.CharField(max_length=10, choices=CHOICES_EFECTO_PAGO, blank=True)
    descarga_grabacion = models.BooleanField(
        default=False,
        help_text=_(
            'Si está activo, al grabar una gestión de llamada con este resultado el sistema '
            'busca y guarda la grabación de la llamada en pbxip.cl. Úsalo solo para resultados '
            'que impliquen contacto efectivo con el cliente (retención legal de 2 años).'
        )
    )
    actualizado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        help_text=_('Último usuario que configuró este resultado (ej. quién activó descarga_grabacion).')
    )

    class Meta:
        ordering = ('nombre',)
        # No alcanza con (cartera, nombre): en Tanner el mismo nombre de respuesta se repite
        # bajo distinto tipo_contacto con codigos distintos (ej. "OTROS" existe para DIRECTO,
        # cod 124, y para DIRECTO AVAL, cod 222). Para Galgo tipo_contacto queda vacio, asi que
        # (cartera, nombre, '') sigue siendo unico ahi igual que antes.
        unique_together = ('cartera', 'nombre', 'tipo_contacto')

    def __str__(self):
        return f"{self.cartera.nombre} / {self.nombre}"


class Action(models.Model):
    CHOICES_TARGET = [
        ('principal', _('Principal')),
        ('aval', _('Aval')),
    ]

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='actions')
    op = models.CharField(max_length=16, editable=False, null=True, blank=True)
    subcartera = models.ForeignKey('cartera.Subcartera', on_delete=models.PROTECT, editable=False, null=True, blank=True)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, editable=False, null=True, blank=True)

    target = models.CharField(_('Target'), max_length=10, choices=CHOICES_TARGET, null=True, blank=True)
    medio = models.ForeignKey(Medio, on_delete=models.PROTECT, related_name='acciones', verbose_name=_('Medio'))
    resultado = models.ForeignKey(Resultado, on_delete=models.PROTECT, related_name='acciones', verbose_name=_('Resultado'))
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name=_('User'))
    comment = models.TextField(_('Comment'), blank=True)

    phone = models.ForeignKey(Phone, on_delete=models.SET_NULL, null=True, blank=True, related_name='actions')
    email = models.EmailField(_('Email'), null=True, blank=True)

    fecha_compromiso = models.DateField(_('Fecha de compromiso de pago'), null=True, blank=True)
    # Algunos reportes de cartera (ej. Nuevo Capital, col "Monto Compromiso") piden ademas el
    # monto comprometido. En pesos, sin decimales.
    monto_compromiso = models.PositiveIntegerField(_('Monto de compromiso'), null=True, blank=True)

    created_at = models.DateTimeField(_('Created At'), auto_now_add=True)

    create_payment_commitment = models.BooleanField(_('Create Payment Commitment'), default=False)
    create_payment = models.BooleanField(_('Create Payment'), default=False)
    convert_debt_free = models.BooleanField(_('Convert Debt Free'), default=False)

    def save(self, *args, **kwargs):
        if self.lead:
            self.op = self.lead.op
            self.subcartera = self.lead.subcartera
            self.team = self.lead.team
        # Automatically set target if phone or email is selected and target is not set
        if not self.target:
            if self.phone:
                self.target = 'principal' if self.phone.phone_type == Phone.PRINCIPAL else 'aval'
            elif self.email:
                id_demographics = IDDemographics.objects.filter(lead=self.lead).first()
                if id_demographics and self.email == id_demographics.principal_email:
                    self.target = 'principal'
                elif AvalDemographics.objects.filter(id_demographics__lead=self.lead, aval_email=self.email).exists():
                    self.target = 'aval'
        if self.resultado_id:
            self.create_payment_commitment = self.resultado.crea_compromiso
        super().save(*args, **kwargs)
        if self.fecha_compromiso and self.lead_id:
            Lead.objects.filter(pk=self.lead_id).update(fecha_compromiso_pago=self.fecha_compromiso)
        # Si la gestion generó un compromiso de pago (resultado con crea_compromiso y una fecha),
        # se materializa como un PaymentCommitment consultable aparte.
        if self.create_payment_commitment and self.fecha_compromiso:
            PaymentCommitment.objects.update_or_create(
                action=self,
                defaults={
                    'lead': self.lead,
                    'subcartera': self.subcartera,
                    'fecha_compromiso': self.fecha_compromiso,
                    'monto': self.monto_compromiso,
                    'comentario': self.comment,
                    'created_by': self.user,
                },
            )
        # El status del lead se calcula solo, a partir del resultado de la gestion.
        if self.lead_id and self.resultado_id:
            from .status_logic import apply_status, compute_status
            apply_status(self.lead, compute_status(self.resultado, self.fecha_compromiso), changed_by=self.user)

    def __str__(self):
        return f"{self.medio.nombre} for {self.lead.op} on {self.created_at}"

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('Action')
        verbose_name_plural = _('Actions')


class PaymentCommitment(models.Model):
    """Compromiso de pago acordado con el cliente durante una gestión."""

    action = models.OneToOneField(Action, on_delete=models.CASCADE, related_name='payment_commitment')
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='payment_commitments')
    subcartera = models.ForeignKey('cartera.Subcartera', on_delete=models.PROTECT, related_name='payment_commitments')
    fecha_compromiso = models.DateField(_('Fecha de compromiso'))
    monto = models.PositiveIntegerField(_('Monto'), null=True, blank=True)
    comentario = models.TextField(_('Comentario'), blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_compromiso', '-created_at']
        verbose_name = _('Compromiso de pago')
        verbose_name_plural = _('Compromisos de pago')

    @property
    def op(self):
        return self.lead.op

    @property
    def cartera(self):
        return self.subcartera.cartera

    def __str__(self):
        return f"Compromiso {self.lead.op} - {self.fecha_compromiso}"


class PendingPbxCall(models.Model):
    """A call just originated through pbxip.cl, awaiting its CDR/recording to show up."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pending_pbx_calls')
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='pending_pbx_calls')
    phone = models.ForeignKey(Phone, on_delete=models.SET_NULL, null=True, blank=True)
    # Set once the collector saves the resulting gestión; determines whether the recording
    # should actually be fetched (only "descarga_grabacion" resultados keep their audio).
    action = models.ForeignKey('Action', on_delete=models.SET_NULL, null=True, blank=True, related_name='pbx_calls')
    destination = models.CharField(max_length=20)
    requested_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f"Pending call to {self.destination} for lead {self.lead.op} ({'resuelta' if self.resolved else 'pendiente'})"


class CallRecording(models.Model):
    pending_call = models.ForeignKey(PendingPbxCall, on_delete=models.SET_NULL, null=True, blank=True, related_name='recordings')
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='call_recordings')
    action = models.ForeignKey(Action, on_delete=models.SET_NULL, null=True, blank=True, related_name='call_recordings')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    cdr_id = models.CharField(max_length=100)
    month = models.CharField(max_length=6)
    destination = models.CharField(max_length=20, blank=True)
    call_date = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    audio_file = models.FileField(upload_to='call_recordings/%Y/%m/')
    # Ley: solo se retienen 2 años las llamadas con contacto efectivo con el cliente.
    retention_until = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('cdr_id', 'month')

    def save(self, *args, **kwargs):
        if not self.retention_until:
            base_date = (self.call_date or timezone.now()).date()
            self.retention_until = base_date + timedelta(days=730)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Grabación {self.cdr_id} - {self.lead.op}"


class Payment(models.Model):
    """
    Pago registrado de un cliente. Es independiente de las gestiones (Action): un pago se
    ingresa por su propio formulario, con su comprobante (imagen/PDF) que queda accesible
    para admin y en el detalle del lead.
    """
    TIPO_PIE = 'pie'
    TIPO_CUOTA = 'cuota'
    CHOICES_TIPO = [
        (TIPO_PIE, _('Pie')),
        (TIPO_CUOTA, _('Cuota')),
    ]

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='payments')
    # Se heredan del lead al guardar (no se editan a mano), para poder agrupar/reportar por cartera.
    subcartera = models.ForeignKey(
        'cartera.Subcartera', on_delete=models.PROTECT, related_name='payments',
        editable=False, null=True, blank=True,
    )
    monto = models.PositiveIntegerField(_('Monto'))
    fecha = models.DateField(_('Fecha de pago'))
    tipo = models.CharField(_('Tipo'), max_length=10, choices=CHOICES_TIPO, default=TIPO_CUOTA)
    comprobante = models.FileField(
        _('Comprobante'), upload_to='payment_receipts/%Y/%m/', null=True, blank=True,
        validators=[FileExtensionValidator(['png', 'jpg', 'jpeg', 'pdf'])],
        help_text=_('Imagen (PNG/JPG) o PDF del comprobante de pago.'),
    )
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments_created')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha', '-created_at']
        verbose_name = _('Pago')
        verbose_name_plural = _('Pagos')

    def save(self, *args, **kwargs):
        if self.lead_id and not self.subcartera_id:
            self.subcartera = self.lead.subcartera
        super().save(*args, **kwargs)
        # Un pago real es la unica via a "pagando" en carteras sin gestion de pago (Tanner,
        # Nuevo Capital). "Al dia" no es automatico por pago: solo por el resultado Galgo
        # "PAGO / AL DIA" (via compute_status) o por el override manual de supervisor.
        if self.lead_id:
            from .status_logic import apply_status
            apply_status(self.lead, Lead.PAGANDO, changed_by=self.created_by)

    @property
    def op(self):
        return self.lead.op

    @property
    def cartera(self):
        return self.subcartera.cartera if self.subcartera else None

    def __str__(self):
        return f"Pago {self.lead.op} - {self.monto} ({self.fecha})"
