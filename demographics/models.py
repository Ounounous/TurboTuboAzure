from django.db import models
from lead.models import Lead


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
        return self.lead.cartera


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

    @property
    def op(self):
        return self.lead.op

    @property
    def cartera(self):
        return self.lead.cartera

    def __str__(self):
        return f"{self.phone_number}"
    
class IDDemographics(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, null=True, blank=True)
    principal_phones = models.ManyToManyField(Phone, related_name='id_demographics_principal_phone', limit_choices_to={'phone_type': Phone.PRINCIPAL}, blank=True)
    principal_email = models.EmailField(max_length=255, blank=True)
    principal_address = models.TextField(blank=True)

    @property
    def op(self):
        return self.lead.op

    @property
    def cartera(self):
        return self.lead.cartera

    def __str__(self):
        return f"{self.op} - {self.cartera}"
    
class AvalDemographics(models.Model):
    id_demographics = models.OneToOneField(IDDemographics, on_delete=models.CASCADE, null=True, blank=True)
    aval_phones = models.ManyToManyField(Phone, related_name='aval_demographics_aval_phone', limit_choices_to={'phone_type': Phone.AVAL}, blank=True)
    aval_name = models.CharField(max_length=255)
    aval_rut = models.CharField(max_length=15)
    aval_dv = models.CharField(max_length=1, null=True, blank=True)
    aval_email = models.EmailField(max_length=255, null=True, blank=True)
    aval_address = models.TextField(null=True, blank=True)

    @property
    def op(self):
        return self.id_demographics.op

    @property
    def cartera(self):
        return self.id_demographics.cartera

    def __str__(self):
        return f"{self.aval_name} - {self.aval_rut}-{self.aval_dv} - {self.op} - {self.cartera}"