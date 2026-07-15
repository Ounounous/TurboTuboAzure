from django import forms
from .models import Action, Lead, Medio, Resultado
from demographics.models import Phone, IDDemographics, AvalDemographics
import logging

logger = logging.getLogger(__name__)

class LeadSearchForm(forms.Form):
    query = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Search by OP, RUT, or Aval RUT...'})
    )

class DemographicSelectionForm(forms.Form):
    phone = forms.ModelChoiceField(queryset=Phone.objects.none(), required=False)
    email = forms.ChoiceField(choices=[], required=False)

    def __init__(self, *args, **kwargs):
        lead = kwargs.pop('lead', None)
        super().__init__(*args, **kwargs)

        if lead:
            # Filter phones related to the lead
            self.fields['phone'].queryset = Phone.objects.filter(lead=lead)
            self.fields['phone'].label_from_instance = lambda \
                obj: f'{obj.phone_number} ({obj.get_phone_type_display()})'

            # Email choice field setup
            id_demographics = IDDemographics.objects.filter(lead=lead).first()
            aval_demographics = AvalDemographics.objects.filter(id_demographics=id_demographics)

            email_choices = []
            if id_demographics and id_demographics.principal_email:
                email_choices.append(
                    (id_demographics.principal_email, f'{id_demographics.principal_email} (principal)'))
            for aval in aval_demographics:
                if aval.aval_email:
                    email_choices.append((aval.aval_email, f'{aval.aval_email} (aval)'))

            self.fields['email'].choices = email_choices



class ActionForm(forms.ModelForm):
    class Meta:
        model = Action
        fields = [
            'medio',
            'resultado',
            'comment',
            'fecha_compromiso',
            'monto_compromiso',
        ]
        widgets = {
            'fecha_compromiso': forms.DateInput(attrs={'type': 'date'}),
            'monto_compromiso': forms.NumberInput(attrs={'min': 0, 'placeholder': 'Monto en pesos'}),
        }
        labels = {
            'fecha_compromiso': 'Fecha de compromiso de pago',
            'monto_compromiso': 'Monto del compromiso ($)',
        }

    def __init__(self, *args, **kwargs):
        cartera = kwargs.pop('cartera', None)
        canal = kwargs.pop('canal', None)
        super().__init__(*args, **kwargs)

        medios_qs = Medio.objects.none()
        resultados_qs = Resultado.objects.none()
        if cartera and canal:
            medios_qs = Medio.objects.filter(cartera=cartera, canal=canal)
        if cartera:
            # Medio y Resultado son independientes: el resultado se elige de la lista
            # completa de la cartera, sin filtrar por el medio elegido.
            resultados_qs = Resultado.objects.filter(cartera=cartera)

        self.fields['medio'].queryset = medios_qs
        self.fields['resultado'].queryset = resultados_qs
        self.fields['medio'].required = True
        self.fields['resultado'].required = True
        self.fields['fecha_compromiso'].required = False
        self.fields['monto_compromiso'].required = False

        logger.debug(f"Form initialized with fields: {self.fields}")

    def clean(self):
        cleaned_data = super().clean()

        medio = cleaned_data.get('medio')
        resultado = cleaned_data.get('resultado')
        fecha_compromiso = cleaned_data.get('fecha_compromiso')

        if resultado and resultado.requiere_fecha_pago and not fecha_compromiso:
            self.add_error('fecha_compromiso', 'Este resultado requiere una fecha de compromiso/pago.')

        logger.debug(f"Cleaned data - Medio: {medio}, Resultado: {resultado}, Fecha: {fecha_compromiso}")

        return cleaned_data