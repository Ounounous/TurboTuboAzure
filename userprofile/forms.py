import logging

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache

from .models import Userprofile

logger = logging.getLogger(__name__)

INPUT_CLASS = 'w-full my-4 py-4 px-6 rounded-xl bg-gray-100'

# Proteccion contra fuerza bruta desde el BACKEND (sin captcha que moleste al cobrador que olvida
# su clave): a los N fallos, esta IP queda bloqueada un rato. Se bloquea por IP, no por usuario.
LOGIN_THROTTLE_MAX_ATTEMPTS = 5          # a los 5 fallos, lockout temporal de esta IP
LOGIN_THROTTLE_WINDOW_SECONDS = 5 * 60
LOGIN_THROTTLE_LOCKOUT_SECONDS = 1 * 60   # bloqueo corto: frena un ataque sin castigar al que se equivoca


def _client_ip(request):
    """IP del cliente segun la ve el borde de Azure. App Service agrega la IP real como ULTIMO
    valor de X-Forwarded-For; los valores anteriores los puede FALSIFICAR el cliente. Tomar el
    primero (como antes) permitia evadir el throttle rotando una IP inventada en la cabecera --
    se toma el ultimo, que lo pone la infraestructura y el cliente no controla."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        candidato = forwarded.split(',')[-1].strip()
        # Azure manda "ip:puerto" -- quitar el puerto (solo IPv4, el caso de App Service).
        if candidato.count(':') == 1 and '.' in candidato:
            candidato = candidato.rsplit(':', 1)[0]
        return candidato or 'unknown'
    return request.META.get('REMOTE_ADDR', 'unknown')


def _cache_get(key, default=None):
    """Lectura de cache que NO tumba el login si Redis se cae. El backend Redis de Django propaga
    los errores de conexion (a diferencia de memcached); sin este guard, un Redis caido dejaba el
    login con error 500. Si el cache no responde, se degrada a 'sin throttle' (mejor disponible que
    bloqueado) y se loguea."""
    try:
        return cache.get(key, default)
    except Exception as exc:
        logger.warning(f'login throttle: cache no disponible ({exc}); se degrada sin throttle')
        return default


def _cache_set(key, value, timeout):
    try:
        cache.set(key, value, timeout)
    except Exception:
        pass


def _cache_delete(key):
    try:
        cache.delete(key)
    except Exception:
        pass


class LoginForm(AuthenticationForm):
    # Mensajes de error en espanol. 'invalid_login' no distingue cual campo fallo (mejor UX y no
    # le confirma a un atacante si el usuario existe).
    error_messages = {
        'invalid_login': 'Usuario o contraseña incorrectos.',
        'inactive': 'Esta cuenta está inactiva.',
    }

    username = forms.CharField(label='Usuario', widget=forms.TextInput(attrs={
        'placeholder': 'Usuario',
        'class': INPUT_CLASS,
    }))
    password = forms.CharField(label='Contraseña', widget=forms.PasswordInput(attrs={
        'placeholder': 'Contraseña',
        'class': INPUT_CLASS,
    }))

    def clean(self):
        # Se bloquea por IP, NO por usuario: bloquear por usuario dejaria que cualquiera tumbe
        # la cuenta de otra persona a proposito fallando el password repetidas veces. Se revisa
        # el lockout ANTES de autenticar (un intento bloqueado no gasta llamada real a la BD de
        # auth), y se cuenta DESPUES, solo si las credenciales fallaron.
        ip = _client_ip(self.request) if self.request else 'unknown'
        lock_key = f'login_lockout:{ip}'
        if _cache_get(lock_key):
            minutos = LOGIN_THROTTLE_LOCKOUT_SECONDS // 60
            unidad = 'minuto' if minutos == 1 else 'minutos'
            raise forms.ValidationError(
                f'Demasiados intentos fallidos desde esta conexión. Intenta de nuevo en '
                f'{minutos} {unidad}.',
                code='throttled',
            )

        attempts_key = f'login_attempts:{ip}'
        try:
            cleaned_data = super().clean()
        except forms.ValidationError:
            self._contar_fallo(attempts_key, lock_key)
            raise
        _cache_delete(attempts_key)  # login exitoso: resetea el contador de esta IP
        return cleaned_data

    @staticmethod
    def _contar_fallo(attempts_key, lock_key):
        attempts = _cache_get(attempts_key, 0) + 1
        _cache_set(attempts_key, attempts, LOGIN_THROTTLE_WINDOW_SECONDS)
        if attempts >= LOGIN_THROTTLE_MAX_ATTEMPTS:
            _cache_set(lock_key, True, LOGIN_THROTTLE_LOCKOUT_SECONDS)
            _cache_delete(attempts_key)

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