from django.contrib.auth.models import User
from django.db import models
from django.apps import apps

from team.models import Team

class Lead(models.Model):
    GALGO = 'galgo'
    TANNER = 'tanner'

    CHOICES_CARTERA = (
        (TANNER, 'Tanner'),
        (GALGO, 'Galgo'),
    )


    JUDICIAL = 'judicial'
    EXTRAJUDICIAL = 'extra judicial'

    CHOICES_TIPO_COBRANZA = (
        (JUDICIAL, 'Judicial'),
        (EXTRAJUDICIAL, 'Extra judicial')
    )

    INUBICABLE = 'inubicable'
    NO_CONTACTADO = 'no contactado'
    CONTACTADO = 'contactado'
    COMPROMISO = 'compromiso'
    PAGANDO = 'pagando'
    AL_DIA = 'al dia'

    CHOICES_STATUS = (
        (INUBICABLE, 'Inubicable'),
        (NO_CONTACTADO, 'No contactado'),
        (CONTACTADO, 'Contactado'),
        (COMPROMISO, 'Compromiso'),
        (PAGANDO, 'Pagando'),
        (AL_DIA, 'Al dia'),
    )

    VIGENTE = 'vigente'
    CASTIGO = 'castigo'

    CHOICES_CICLO_CARTERA = (
        (VIGENTE, 'Vigente'),
        (CASTIGO, 'Castigo'),
    )


    C1 = 'C1'
    C2 = 'C2'
    C3 = 'C3'
    C4 = 'C4'
    C5 = 'C5'
    C6 = 'C6'
    C7 = 'C7'
    C8 = 'C8'
    C9 = 'C9'
    C10 = 'C10'
    C11 = 'C11'
    C12 = 'C12'
    C13 = 'C13'
    CASTIGO = 'castigo'
    NO_DEFINIDO = 'no definido'
   

    CHOICES_CICLO = (
        (C1, 'C1'),
        (C2, 'C2'), 
        (C3, 'C3'),
        (C4, 'C4'),
        (C5, 'C5'),
        (C6, 'C6'),
        (C7, 'C7'),
        (C8, 'C8'),
        (C9, 'C9'),
        (C10, 'C10'),
        (C11, 'C11'),
        (C12, 'C12'),
        (C13, 'C13'),
        (CASTIGO, 'Castigo'),
        (NO_DEFINIDO, 'No definido'),
    )

    ACTIVO = 'activo'
    SUSPENDIDO = 'suspendido'
    TERMINADO = 'terminado'
   

    CHOICES_ACTIVO = (
        (ACTIVO, 'Activo'),
        (SUSPENDIDO, 'Suspendido'),
        (TERMINADO, 'Terminado'),
    )

    SI = 'si'
    NO = 'no'
   

    CHOICES_AVAL = (
        (SI, 'Si'),
        (NO, 'No'),
    )

    team = models.ForeignKey(Team, related_name='leads', on_delete=models.CASCADE)
    op = models.CharField(max_length=16)
    name = models.CharField(max_length=255)
    rut = models.IntegerField()
    dv = models.CharField(max_length=255)
    saldo_insoluto = models.IntegerField()
    saldo_deuda = models.IntegerField()
    valor_cuota = models.IntegerField()
    cuotas_atrasadas = models.IntegerField()
    cartera = models.CharField(max_length=255, choices=CHOICES_CARTERA, default=GALGO)
    tipo_cobranza = models.CharField(max_length=15, choices=CHOICES_TIPO_COBRANZA, default=EXTRAJUDICIAL)
    status = models.CharField(max_length=15, choices=CHOICES_STATUS, default=NO_CONTACTADO)
    ciclo_cartera = models.CharField(max_length=255, choices=CHOICES_CICLO_CARTERA, default=VIGENTE)
    ciclo = models.CharField(max_length=255, choices=CHOICES_CICLO, default=NO_DEFINIDO)
    activo = models.CharField(max_length=255, choices=CHOICES_ACTIVO, default=ACTIVO)
    tiene_aval = models.CharField(max_length=2, choices=CHOICES_AVAL, default=NO)
    converted_to_client = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, related_name='leads', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    assigned_to = models.ForeignKey(User, related_name='assigned_leads', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ('name',)
    
    def __str__(self):
        return self.op

class StatusChangeLog(models.Model):
    lead = models.ForeignKey('Lead', on_delete=models.CASCADE)
    changed_by = models.ForeignKey(User, on_delete=models.CASCADE)
    new_status = models.CharField(max_length=100)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Lead {self.lead.id} status changed to {self.new_status} by {self.changed_by.username}"

class LeadFile(models.Model):
    team = models.ForeignKey(Team, related_name='lead_files', on_delete=models.CASCADE)
    lead = models.ForeignKey(Lead, related_name='files', on_delete=models.CASCADE)
    file = models.FileField(upload_to='leadfiles/')
    created_by = models.ForeignKey(User, related_name='lead_files', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.created_by.username

class Comment(models.Model):
    team = models.ForeignKey(Team, related_name='lead_comments', on_delete=models.CASCADE)
    lead = models.ForeignKey(Lead, related_name='comments', on_delete=models.CASCADE)
    content = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(User, related_name='lead_comments', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.created_by.username

class LeadAssignment(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='lead_assignments')
    assigned_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='assignments_made')
    assigned_at = models.DateTimeField(auto_now_add=True)