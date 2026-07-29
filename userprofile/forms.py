from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.core.cache import cache

from .models import Userprofile

INPUT_CLASS = 'w-full my-4 py-4 px-6 rounded-xl bg-gray-100'

# Proteccion basica contra fuerza bruta / credential stuffing en el login.
LOGIN_THROTTLE_MAX_ATTEMPTS = 5
LOGIN_THROTTLE_WINDOW_SECONDS = 5 * 60
LOGIN_THROTTLE_LOCKOUT_SECONDS = 15 * 60


def _client_ip(request):
    """IP real del cliente. Azure App Service termina TLS en el proxy y reenvia el origen en
    X-Forwarded-For -- REMOTE_ADDR ahi es la IP interna del proxy, no la del visitante."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={
        'placeholder': 'Your username',
        'class': INPUT_CLASS
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'placeholder': 'Your password',
        'class': INPUT_CLASS
    }))

    def clean(self):
        # Se bloquea por IP, NO por usuario: bloquear por usuario dejaria que cualquiera tumbe
        # la cuenta de otra persona a proposito fallando el password repetidas veces. Se revisa
        # el lockout ANTES de autenticar (un intento bloqueado no gasta llamada real a la BD de
        # auth), y se cuenta DESPUES, solo si las credenciales fallaron.
        ip = _client_ip(self.request) if self.request else 'unknown'
        lock_key = f'login_lockout:{ip}'
        if cache.get(lock_key):
            raise forms.ValidationError(
                'Demasiados intentos fallidos desde esta conexión. Intenta de nuevo en unos minutos.',
                code='throttled',
            )

        attempts_key = f'login_attempts:{ip}'
        try:
            cleaned_data = super().clean()
        except forms.ValidationError:
            attempts = cache.get(attempts_key, 0) + 1
            cache.set(attempts_key, attempts, LOGIN_THROTTLE_WINDOW_SECONDS)
            if attempts >= LOGIN_THROTTLE_MAX_ATTEMPTS:
                cache.set(lock_key, True, LOGIN_THROTTLE_LOCKOUT_SECONDS)
                cache.delete(attempts_key)
            raise
        cache.delete(attempts_key)  # login exitoso: resetea el contador de esta IP
        return cleaned_data

class SignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']
    
    username = forms.CharField(widget=forms.TextInput(attrs={
        'placeholder': 'Your username',
        'class': INPUT_CLASS
    }))
    email = forms.EmailField(widget=forms.EmailInput(attrs={
        'placeholder': 'Your email',
        'class': INPUT_CLASS
    }))
    password1 = forms.CharField(widget=forms.PasswordInput(attrs={
        'placeholder': 'Your password',
        'class': INPUT_CLASS
    }))
    password2 = forms.CharField(widget=forms.PasswordInput(attrs={
        'placeholder': 'Repeat your password',
        'class': INPUT_CLASS
    }))


class ProfileDataForm(forms.Form):
    rut = forms.CharField(
        label='RUT (sin puntos, sin guión, SIN dígito verificador)', required=False,
        help_text='Lo exigen algunos reportes de cartera para identificar al ejecutivo (ej. Tanner, columna "Ejecutivo").'
    )

    def __init__(self, *args, **kwargs):
        self.userprofile = kwargs.pop('userprofile')
        super().__init__(*args, **kwargs)
        self.fields['rut'].initial = self.userprofile.rut

    def save(self):
        self.userprofile.rut = self.cleaned_data['rut']
        self.userprofile.save()
        return self.userprofile


class PbxCredentialsForm(forms.Form):
    pbx_email = forms.CharField(label='Usuario/email en pbxip.cl', required=True)
    pbx_password = forms.CharField(
        label='Contraseña en pbxip.cl', required=False, widget=forms.PasswordInput(render_value=False),
        help_text='Déjala en blanco para mantener la que ya está guardada.'
    )
    pbx_extension = forms.CharField(label='Anexo/extensión', required=True)

    def __init__(self, *args, **kwargs):
        self.userprofile = kwargs.pop('userprofile')
        super().__init__(*args, **kwargs)
        self.fields['pbx_email'].initial = self.userprofile.pbx_email
        self.fields['pbx_extension'].initial = self.userprofile.pbx_extension

    def save(self):
        self.userprofile.pbx_email = self.cleaned_data['pbx_email']
        self.userprofile.pbx_extension = self.cleaned_data['pbx_extension']
        if self.cleaned_data['pbx_password']:
            self.userprofile.pbx_password = self.cleaned_data['pbx_password']
        self.userprofile.save()
        return self.userprofile