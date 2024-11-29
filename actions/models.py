from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from lead.models import Lead
from team.models import Team
from demographics.models import Phone, IDItem, IDDemographics, AvalDemographics

class Action(models.Model):
    CHOICES_ACTION_TYPE = [
        ('whatsapp', _('WhatsApp')),
        ('email', _('Email')),
        ('phone_call', _('Phone call')),
        ('whatsapp_call', _('WhatsApp call')),
        ('ivr_audio', _('IVR_audio')),
        ('ivr_mute', _('IVR_mute'))
    ]

    CHOICES_RESULT = [
        ('aporta_informacion_deudor_principal', _('Aporta información deudor principal')),
        ('buzon_de_voz', _('Buzón de voz')),
        ('compromiso_de_pago', _('Compromiso de pago')),
        ('con_seguro_en_tramite', _('Con seguro en trámite')),
        ('corta_llamado', _('Corta llamado')),
        ('dacion', _('Dación')),
        ('email_invalido', _('Email inválido')),
        ('fono_no_corresponde', _('Fono no corresponde')),
        ('ivr_mudo_enviado', _('IVR mudo enviado')),
        ('msj_de_contacto', _('Msj de contacto')),
        ('msj_de_seguimiento', _('Msj de seguimiento')),
        ('no_responde', _('No responde')),
        ('pago_al_dia', _('Pago al día')),
        ('pago_contenido', _('Pago contenido')),
        ('recibe_recado', _('Recibe recado')),
        ('reclamo', _('Reclamo')),
        ('recordatorio_de_compromiso', _('Recordatorio de compromiso')),
        ('renegociacion', _('Renegociación')),
        ('responde_msj_contacto_sin_fecha', _('Responde msj contacto sin fecha')),
        ('sin_whatsapp', _('Sin WhatsApp')),
        ('solicita_llamado_posterior', _('Solicita llamado posterior')),
        ('telefono_congestionado', _('Teléfono congestionado')),
        ('volver_a_llamar', _('Volver a llamar')),
    ]

    CHOICES_TARGET = [
        ('principal', _('Principal')),
        ('aval', _('Aval')),
    ]

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='actions')
    op = models.CharField(max_length=16, editable=False, null=True, blank=True)
    cartera = models.CharField(max_length=255, editable=False, choices=Lead.CHOICES_CARTERA, null=True, blank=True)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, editable=False, null=True, blank=True)

    target = models.CharField(_('Target'), max_length=10, choices=CHOICES_TARGET, null=True, blank=True)
    action_type = models.CharField(_('Action Type'), max_length=20, choices=CHOICES_ACTION_TYPE)
    result = models.CharField(_('Result'), max_length=255, choices=CHOICES_RESULT)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name=_('User'))
    comment = models.TextField(_('Comment'), blank=True)

    phone = models.ForeignKey(Phone, on_delete=models.SET_NULL, null=True, blank=True, related_name='actions')
    email = models.EmailField(_('Email'), null=True, blank=True)

    created_at = models.DateTimeField(_('Created At'), auto_now_add=True)

    create_payment_commitment = models.BooleanField(_('Create Payment Commitment'), default=False)
    create_payment = models.BooleanField(_('Create Payment'), default=False)
    convert_debt_free = models.BooleanField(_('Convert Debt Free'), default=False)

    def save(self, *args, **kwargs):
        if self.lead:
            self.op = self.lead.op
            self.cartera = self.lead.cartera
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
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_action_type_display()} for {self.lead.op} on {self.created_at}"

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('Action')
        verbose_name_plural = _('Actions')