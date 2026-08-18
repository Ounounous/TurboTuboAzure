"""Form de configuracion de reportes automaticos por email (ver actions/models.py:
ReporteAutomaticoConfig). Vive en actions/ (junto al resto de la logica de reportes) aunque la
pantalla que lo usa esta en cartera/ -- mismo criterio que ya usa el proyecto para reportes."""
from django import forms
from django.core.validators import validate_email

from cartera.models import Cartera

from .models import ReporteAutomaticoConfig


class ReporteAutomaticoConfigForm(forms.ModelForm):
    class Meta:
        model = ReporteAutomaticoConfig
        fields = (
            'tipo_reporte', 'subcarteras', 'periodicidad', 'cada_x_dias', 'saltar_fines_de_semana',
            'hora_envio', 'destinatarios_to', 'destinatarios_cc', 'destinatarios_cco',
            'metodo_envio', 'remitente_from', 'asunto_personalizado',
        )
        widgets = {
            'subcarteras': forms.CheckboxSelectMultiple(),
            'destinatarios_to': forms.Textarea(attrs={'rows': 2, 'placeholder': 'data@cliente.com, otro@cliente.com'}),
            'destinatarios_cc': forms.Textarea(attrs={'rows': 2}),
            'destinatarios_cco': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Para dueños/supervisores, sin que el resto lo sepa'}),
        }

    def __init__(self, *args, cartera=None, **kwargs):
        self.cartera = cartera
        super().__init__(*args, **kwargs)
        self.fields['subcarteras'].queryset = cartera.subcarteras.all() if cartera else self.fields['subcarteras'].queryset.none()
        self.fields['subcarteras'].required = False
        self.fields['subcarteras'].help_text = 'Sin elegir ninguna = toda la cartera.'

        # El reporte "estandar" solo tiene sentido si la cartera tiene un formato regulatorio
        # propio (hoy, Tanner) -- no ofrecerlo si no aplica.
        if not cartera or cartera.arbol_tipo != Cartera.ARBOL_TANNER:
            self.fields['tipo_reporte'].choices = [
                c for c in ReporteAutomaticoConfig.CHOICES_TIPO_REPORTE
                if c[0] != ReporteAutomaticoConfig.TIPO_ESTANDAR
            ]

        # Azure Communication Services es un placeholder en el modelo (ver ReporteAutomaticoConfig)
        # -- no esta implementado, no se ofrece en el form todavia.
        self.fields['metodo_envio'].choices = [
            c for c in ReporteAutomaticoConfig.CHOICES_METODO_ENVIO
            if c[0] == ReporteAutomaticoConfig.METODO_SMTP
        ]

    def _clean_emails(self, field_name, obligatorio):
        raw = self.cleaned_data.get(field_name, '')
        emails = [e.strip() for e in raw.split(',') if e.strip()]
        if obligatorio and not emails:
            raise forms.ValidationError('Ingresa al menos un email.')
        for email in emails:
            validate_email(email)
        return raw

    def clean_destinatarios_to(self):
        return self._clean_emails('destinatarios_to', obligatorio=True)

    def clean_destinatarios_cc(self):
        return self._clean_emails('destinatarios_cc', obligatorio=False)

    def clean_destinatarios_cco(self):
        return self._clean_emails('destinatarios_cco', obligatorio=False)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('periodicidad') == ReporteAutomaticoConfig.PERIODICIDAD_CADA_X_DIAS:
            if not cleaned.get('cada_x_dias'):
                self.add_error('cada_x_dias', 'Indica cada cuántos días enviar.')
        return cleaned
