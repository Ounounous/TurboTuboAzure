from django import forms
from django.utils import timezone
from .models import Action, Lead, Medio, Resultado, Payment
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
            # Telefonos del lead, EXCLUYENDO los blacklisted (no se pueden gestionar). Los
            # "no existe" / "fuera de servicio" si se ofrecen (aun se puede intentar).
            self.fields['phone'].queryset = Phone.objects.filter(lead=lead).exclude(
                phone_number_status=Phone.BLACKLISTED
            )
            self.fields['phone'].label_from_instance = lambda \
                obj: f'{obj.phone_number} ({obj.get_phone_type_display()})'

            # Correos: mismo criterio, se ofrecen salvo los blacklisted.
            id_demographics = IDDemographics.objects.filter(lead=lead).first()
            aval_demographics = AvalDemographics.objects.filter(id_demographics=id_demographics)

            from demographics.models import Email, CONTACT_BLACKLISTED

            email_choices = []
            if id_demographics and id_demographics.principal_email and id_demographics.principal_email_status != 'blacklisted':
                email_choices.append(
                    (id_demographics.principal_email, f'{id_demographics.principal_email} (principal)'))
            # Correos adicionales del lead (modelo Email), mismo criterio: se ofrecen salvo blacklisted.
            for em in Email.objects.filter(lead=lead).exclude(email_status=CONTACT_BLACKLISTED):
                email_choices.append((em.email, f'{em.email} (adicional)'))
            for aval in aval_demographics:
                if aval.aval_email and aval.aval_email_status != 'blacklisted':
                    email_choices.append((aval.aval_email, f'{aval.aval_email} (aval)'))

            self.fields['email'].choices = email_choices

    def clean(self):
        """Exige elegir exactamente telefono O correo, nunca ambos ni ninguno. Sin esto, el JS
        del paso 2 puede dejar los dos hidden inputs (phone/email) con valor -- ej. el telefono se
        auto-preselecciono por ser la unica opcion, y despues el cobrador eligio un correo sin que
        el hidden de telefono se limpiara -- y el paso 3 terminaba gestionando por telefono aunque
        el cobrador haya elegido correo (bug reportado: la gestion "se pasaba sola" al telefono)."""
        cleaned = super().clean()
        phone = cleaned.get('phone')
        email = cleaned.get('email')
        if phone and email:
            raise forms.ValidationError('Elige solo un teléfono o un correo, no ambos.')
        if not phone and not email:
            raise forms.ValidationError('Elige un teléfono o un correo para continuar.')
        return cleaned


class AddPhoneQuickForm(forms.Form):
    """Agregar un teléfono nuevo sin salir del flujo de gestión (paso 2). Queda activo por
    default -- cualquier usuario logueado puede usarlo, no solo supervisor+."""
    phone_number = forms.CharField(max_length=20, label='Nuevo teléfono')

    def clean_phone_number(self):
        value = self.cleaned_data['phone_number'].strip()
        if not any(c.isdigit() for c in value):
            raise forms.ValidationError('Ingresa un número de teléfono válido.')
        return value


class AddEmailQuickForm(forms.Form):
    """Igual que AddPhoneQuickForm pero para el correo principal. Solo se ofrece cuando el lead
    todavía no tiene uno (ver MultiStepActionView) -- evita pisar un correo ya cargado."""
    email = forms.EmailField(label='Nuevo correo')


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['monto', 'fecha', 'tipo', 'comentario', 'comprobante']
        widgets = {
            'fecha': forms.DateInput(attrs={'type': 'date'}),
            'monto': forms.NumberInput(attrs={'min': 0, 'placeholder': 'Monto en pesos'}),
            'comprobante': forms.ClearableFileInput(attrs={'accept': '.png,.jpg,.jpeg,.pdf'}),
        }
        labels = {
            'monto': 'Monto ($)',
            'fecha': 'Fecha del pago',
            'tipo': 'Tipo',
            'comentario': 'Comentario',
            'comprobante': 'Comprobante (PNG/JPG/PDF)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['monto'].required = True
        self.fields['fecha'].required = True
        self.fields['comprobante'].required = False


class ActionForm(forms.ModelForm):
    class Meta:
        model = Action
        fields = [
            'medio',
            'origen',
            'resultado',
            'comment',
            'fecha_compromiso',
            'monto_compromiso',
        ]
        widgets = {
            'fecha_compromiso': forms.DateInput(attrs={'type': 'date'}),
            'monto_compromiso': forms.NumberInput(attrs={'min': 0, 'placeholder': 'Monto en pesos'}),
            'origen': forms.RadioSelect,
        }
        labels = {
            'fecha_compromiso': 'Fecha de compromiso de pago',
            'monto_compromiso': 'Monto del compromiso ($)',
            'origen': '¿Quién inició el contacto?',
        }

    def __init__(self, *args, **kwargs):
        cartera = kwargs.pop('cartera', None)
        canal = kwargs.pop('canal', None)
        es_cobrador = kwargs.pop('es_cobrador', False)
        super().__init__(*args, **kwargs)

        medios_qs = Medio.objects.none()
        resultados_qs = Resultado.objects.none()
        if cartera and canal:
            # Solo medios de gestión manual: la llamada directa, WhatsApp y correo saliente.
            # Los medios masivos (IVR, SMS, discador, bot, entrantes) se cargan por Excel.
            medios_qs = Medio.objects.filter(cartera=cartera, canal=canal, permite_manual=True)
        if cartera:
            # Medio y Resultado son independientes: el resultado se elige de la lista
            # completa de la cartera, sin filtrar por el medio elegido. permite_manual=False
            # saca los resultados de campaña/backoffice (ej. Tanner PAC/Venta Directa) que no
            # son para que un gestor los elija a mano -- la carga masiva/Excel si los acepta.
            resultados_qs = Resultado.objects.filter(cartera=cartera, permite_manual=True)
            if es_cobrador:
                # Un cobrador solo puede registrar Directo/Sin contacto en Tanner y Nuevo
                # Capital (nada de Indirecto/Directo aval/Accion masiva/Recibidos) -- eso no
                # toca el arbol ni la carga masiva, solo el desplegable de este formulario.
                # admin/owner/supervisor siguen viendo la lista completa.
                from .gestion_defaults import TIPO_CONTACTO_COLLECTOR_WHITELIST
                permitidos = TIPO_CONTACTO_COLLECTOR_WHITELIST.get((cartera.nombre or '').strip())
                if permitidos:
                    resultados_qs = resultados_qs.filter(tipo_contacto__in=permitidos)

        self.fields['medio'].queryset = medios_qs
        self.fields['resultado'].queryset = resultados_qs
        self.fields['medio'].required = True
        self.fields['resultado'].required = True
        self.fields['fecha_compromiso'].required = False
        self.fields['monto_compromiso'].required = False

        # Solo Tanner tiene la ambiguedad de origen en su reporte (un mismo resultado puede
        # darse por contacto saliente o entrante, ver actions/tanner_report.py). Galgo y Cartera
        # Propia no reportan origen; Nuevo Capital ya lo resuelve con medios separados
        # ("LLAMADA RECIBIDA", etc, Medio.es_inbound) sin necesitar que el gestor elija nada.
        # Para esas carteras el campo queda oculto y guarda el default (saliente).
        self.mostrar_origen = bool(cartera) and (cartera.nombre or '').strip().upper() == 'TANNER'
        if not self.mostrar_origen:
            self.fields['origen'].widget = forms.HiddenInput()
            self.fields['origen'].required = False
        # localdate(), no date.today(): el servidor puede correr en otro huso horario (ej. UTC en
        # Azure) -- localdate() usa TIME_ZONE=America/Santiago (settings.py), date.today() usaria
        # la hora del sistema y desfasaria "hoy" cerca de la medianoche.
        self.fields['fecha_compromiso'].widget.attrs['min'] = timezone.localdate().isoformat()

        logger.debug(f"Form initialized with fields: {self.fields}")

    def clean(self):
        cleaned_data = super().clean()

        medio = cleaned_data.get('medio')
        resultado = cleaned_data.get('resultado')
        fecha_compromiso = cleaned_data.get('fecha_compromiso')

        if resultado and resultado.requiere_fecha_pago and not fecha_compromiso:
            self.add_error('fecha_compromiso', 'Este resultado requiere una fecha de compromiso/pago.')

        if fecha_compromiso and fecha_compromiso < timezone.localdate():
            self.add_error('fecha_compromiso', 'La fecha de compromiso no puede ser anterior a hoy.')

        logger.debug(f"Cleaned data - Medio: {medio}, Resultado: {resultado}, Fecha: {fecha_compromiso}")

        return cleaned_data