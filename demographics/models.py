from django.contrib.auth.models import User
from django.db import models
from lead.models import Lead

# Estado de un dato de contacto (telefono o correo). Mismos valores que usa Phone, con etiquetas
# en español para las pantallas de "Estado de demografía".
CONTACT_ACTIVE = 'active'
CONTACT_NON_EXISTENT = 'non-existent'
CONTACT_OUT_OF_SERVICE = 'out of service'
CONTACT_BLACKLISTED = 'blacklisted'

CHOICES_CONTACT_STATUS = (
    (CONTACT_ACTIVE, 'Activo'),
    (CONTACT_NON_EXISTENT, 'No existe'),
    (CONTACT_OUT_OF_SERVICE, 'Fuera de servicio'),
    (CONTACT_BLACKLISTED, 'Blacklist'),
)


class Email(models.Model):
    """Correos ADICIONALES de un lead, mas alla del principal (IDDemographics.principal_email) y
    del aval. Permite tener varios correos por lead: el primero que se carga queda como principal
    (integra con reportes, carga masiva y 'Estado de correos'); estos son los extra, que se pueden
    agregar y seleccionar en el paso 2 de gestion como cualquier otro dato de contacto."""
    lead = models.ForeignKey(Lead, related_name='emails', on_delete=models.CASCADE)
    email = models.EmailField(max_length=255)
    email_status = models.CharField(max_length=20, choices=CHOICES_CONTACT_STATUS, default=CONTACT_ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def is_reachable(self):
        return self.email_status != CONTACT_BLACKLISTED

    def __str__(self):
        return f"{self.email} ({self.lead.op})"


class IDItem(models.Model):
    #tipo de bien
    AUTO = 'auto'
    MOTO = 'moto'
    INMUEBLE = 'inmueble'
    OTRO = 'otro'


    CHOICES_ITEM_TYPE = (
        (AUTO, 'Auto'),
        (MOTO, 'Moto'),
        (INMUEBLE, 'Inmueble'),
        (OTRO, 'Otro'),
    )

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, null=True, blank=True)
    item_type = models.CharField(max_length=255, choices=CHOICES_ITEM_TYPE, default=AUTO)
    patente = models.CharField(max_length=10, null=True, blank=True)
    marca = models.CharField(max_length=255, null=True, blank=True)
    modelo = models.CharField(max_length=255, null=True, blank=True)
    año = models.IntegerField(null=True, blank=True)
    # other fields as needed


    @property
    def op(self):
        return self.lead.op


    @property
    def cartera(self):
        return self.lead.subcartera.cartera.nombre


    def __str__(self):
        return f"{self.item_type} - {self.patente or ''} - {self.marca or ''} - {self.modelo or ''}"
    
class Phone(models.Model):
    
    ACTIVE = 'active'
    NON_EXISTENT = 'non-existent'
    OUT_OF_SERVICE = 'out of service'
    BLACKLISTED = 'blacklisted'

    CHOICES_PHONE_NUMBER_STATUS = (
        (ACTIVE, 'Active'),
        (NON_EXISTENT, 'Non-existent'),
        (OUT_OF_SERVICE, 'Out of service'),
        (BLACKLISTED, 'Blacklisted'),
    )

    PRINCIPAL = 'principal'
    AVAL = 'aval'

    CHOICES_PHONE_TYPE = (
        (PRINCIPAL, 'Principal'),
        (AVAL, 'Aval'),
    )

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, null=True, blank=True)
    phone_number = models.CharField(max_length=20)
    phone_type = models.CharField(max_length=255, choices=CHOICES_PHONE_TYPE, default=PRINCIPAL)
    phone_number_status = models.CharField(max_length=255, choices=CHOICES_PHONE_NUMBER_STATUS, default=ACTIVE)
    # Disponibilidad de WhatsApp del numero, independiente de su estado: un numero puede seguir
    # sirviendo para llamar (status=active) pero no tener WhatsApp. Lo apaga el resultado
    # "SIN WHATSAPP" / "ENVIO WHATSAPP NO ENTREGADO" o un supervisor a mano.
    whatsapp_activo = models.BooleanField(default=True)

    @property
    def op(self):
        return self.lead.op

    @property
    def cartera(self):
        return self.lead.subcartera.cartera.nombre

    @property
    def es_gestionable(self):
        """Un numero blacklisted no se ofrece ni se puede gestionar."""
        return self.phone_number_status != self.BLACKLISTED

    def __str__(self):
        return f"{self.phone_number}"
    
class IDDemographics(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, null=True, blank=True)
    principal_phones = models.ManyToManyField(Phone, related_name='id_demographics_principal_phone', limit_choices_to={'phone_type': Phone.PRINCIPAL}, blank=True)
    principal_email = models.EmailField(max_length=255, blank=True)
    principal_email_status = models.CharField(max_length=20, choices=CHOICES_CONTACT_STATUS, default=CONTACT_ACTIVE)
    principal_address = models.TextField(blank=True)

    @property
    def op(self):
        return self.lead.op

    @property
    def cartera(self):
        return self.lead.subcartera.cartera.nombre

    def __str__(self):
        return f"{self.op} - {self.cartera}"
    
class AvalDemographics(models.Model):
    id_demographics = models.OneToOneField(IDDemographics, on_delete=models.CASCADE, null=True, blank=True)
    aval_phones = models.ManyToManyField(Phone, related_name='aval_demographics_aval_phone', limit_choices_to={'phone_type': Phone.AVAL}, blank=True)
    aval_name = models.CharField(max_length=255)
    aval_rut = models.CharField(max_length=15)
    aval_dv = models.CharField(max_length=1, null=True, blank=True)
    aval_email = models.EmailField(max_length=255, null=True, blank=True)
    aval_email_status = models.CharField(max_length=20, choices=CHOICES_CONTACT_STATUS, default=CONTACT_ACTIVE)
    aval_address = models.TextField(null=True, blank=True)

    @property
    def op(self):
        return self.id_demographics.op

    @property
    def cartera(self):
        return self.id_demographics.cartera

    def __str__(self):
        return f"{self.aval_name} - {self.aval_rut}-{self.aval_dv} - {self.op} - {self.cartera}"


class ContactExportJob(models.Model):
    """
    Export a Excel de telefonos o correos activos (filtrados igual que la pagina Clientes), para
    alimentar motores externos (ej. la VM de envios). Se arma en el WORKER: el filtro puede
    devolver miles de filas -- una por telefono/correo, no por lead -- y una consulta asi de
    grande no debe frenar el proceso web.
    """
    TELEFONOS = 'telefonos'
    CORREOS = 'correos'
    CHOICES_TIPO = (
        (TELEFONOS, 'Teléfonos'),
        (CORREOS, 'Correos'),
    )

    PENDIENTE = 'pendiente'
    PROCESANDO = 'procesando'
    LISTO = 'listo'
    VACIO = 'vacio'
    ERROR = 'error'
    CHOICES_ESTADO = (
        (PENDIENTE, 'En cola'),
        (PROCESANDO, 'Procesando'),
        (LISTO, 'Listo para descargar'),
        (VACIO, 'Sin datos con esos filtros'),
        (ERROR, 'Falla del servidor'),
    )

    solicitado_por = models.ForeignKey(User, on_delete=models.CASCADE, related_name='exports_contactos')
    tipo = models.CharField(max_length=10, choices=CHOICES_TIPO)
    # Querystring de filtros (los mismos de Clientes) tal como estaba la pantalla al pedir el
    # export -- el worker la vuelve a aplicar para que "descargar filtrados" traiga exactamente
    # lo que se veia en pantalla.
    filtros = models.TextField(blank=True)
    archivo = models.FileField(upload_to='exports/demografia/%Y/%m/', blank=True)
    estado = models.CharField(max_length=12, choices=CHOICES_ESTADO, default=PENDIENTE)
    total_filas = models.PositiveIntegerField(default=0)
    mensaje = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Export de contactos'
        verbose_name_plural = 'Exports de contactos'

    def __str__(self):
        return f"Export {self.tipo} #{self.pk} ({self.estado}) - {self.solicitado_por}"