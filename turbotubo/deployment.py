"""
Settings de PRODUCCION (Azure). Hereda de settings.py y endurece. NO contiene secretos: todo
sale de variables de entorno (App Service Configuration / Key Vault). Si falta un secreto
critico, el arranque FALLA fuerte a proposito -- mejor que correr inseguro.
"""
import os

# Alias SECRET -> SECRET_KEY ANTES de importar settings.py: settings.py exige SECRET_KEY en el
# entorno cuando DEBUG=False y falla duro en el import mismo si falta (ImproperlyConfigured) --
# el chequeo de mas abajo (que sí acepta SECRET como alias) nunca llegaba a ejecutarse porque
# el import de la linea siguiente ya reventaba antes.
if not os.environ.get('SECRET_KEY') and os.environ.get('SECRET'):
    os.environ['SECRET_KEY'] = os.environ['SECRET']

from .settings import *  # noqa
from .settings import BASE_DIR, DATABASES

# --- Secretos: obligatorios en produccion, sin fallback ---
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise RuntimeError('Falta SECRET_KEY (o SECRET) en el entorno de produccion.')

DEBUG = False

# --- Hosts / CSRF ---
# Azure inyecta WEBSITE_HOSTNAME. Se admiten dominios extra por env (coma-separados).
_hosts = [h.strip() for h in os.environ.get('EXTRA_ALLOWED_HOSTS', '').split(',') if h.strip()]
_website = os.environ.get('WEBSITE_HOSTNAME')
if _website:
    _hosts.append(_website)
_hosts.append('169.254.130.4')  # sonda de salud de Azure
ALLOWED_HOSTS = _hosts or ['localhost']
CSRF_TRUSTED_ORIGINS = [f'https://{h}' for h in _hosts if h != '169.254.130.4']

# --- HTTPS / cookies / HSTS ---
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')  # Azure termina TLS en el proxy
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = 'SAMEORIGIN'
# Cierre de sesion por inactividad (control esperado en auditorias tipo ISO/SOC).
SESSION_COOKIE_AGE = int(os.environ.get('SESSION_COOKIE_AGE', str(8 * 60 * 60)))  # 8h
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# --- Estaticos servidos por WhiteNoise (comprimidos + hasheados) ---
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Comprime el HTML dinamico. Va DESPUES de WhiteNoise: WhiteNoise ya sirve los estaticos
    # (comprimidos) y los short-circuita, asi GZip solo ve las paginas dinamicas.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.gzip.GZipMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'userprofile.middleware.ForcePasswordChangeMiddleware',
    'core.middleware.NoStoreAuthenticatedMiddleware',
]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# --- Media en Azure Blob Storage (obligatorio en prod: WhiteNoise no sirve media, y el disco
# del App Service es efimero -- las grabaciones/comprobantes se perderian en cada deploy) ---
_blob_account = os.environ.get('AZURE_STORAGE_ACCOUNT')
_blob_key = os.environ.get('AZURE_STORAGE_KEY')
_blob_conn = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')

STORAGES = {
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
if not (_blob_account or _blob_conn):
    # FALLA FUERTE a proposito. Sin Blob, `default` caia a FileSystemStorage sobre el disco del
    # App Service: unos 10 GB y EFIMERO (se borra en cada despliegue, reinicio o escalado). Ahi
    # van las grabaciones de llamadas -- con retencion legal de 2 anios -- y los comprobantes de
    # pago. El modo silencioso era peor que no arrancar: la app funcionaba, la gente grababa
    # llamadas, y el siguiente despliegue las borraba sin que nadie se enterara.
    #
    # Para levantar produccion hay que definir AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_KEY (o
    # AZURE_STORAGE_CONNECTION_STRING). Si de verdad se quiere arrancar sin almacenamiento
    # persistente (solo pruebas), poner ALLOW_EPHEMERAL_MEDIA=True y asumir la perdida.
    if os.environ.get('ALLOW_EPHEMERAL_MEDIA', 'False') != 'True':
        raise RuntimeError(
            'Falta el almacenamiento de media en produccion: define AZURE_STORAGE_ACCOUNT y '
            'AZURE_STORAGE_KEY (o AZURE_STORAGE_CONNECTION_STRING). Sin esto las grabaciones y '
            'los comprobantes se guardarian en el disco efimero del App Service y se perderian '
            'en el proximo despliegue. Para arrancar igual (solo pruebas): ALLOW_EPHEMERAL_MEDIA=True.'
        )
    STORAGES['default'] = {'BACKEND': 'django.core.files.storage.FileSystemStorage'}
else:
    STORAGES['default'] = {
        'BACKEND': 'storages.backends.azure_storage.AzureStorage',
        'OPTIONS': {
            'account_name': _blob_account,
            'account_key': _blob_key,
            'connection_string': _blob_conn,
            'azure_container': os.environ.get('AZURE_MEDIA_CONTAINER', 'media'),
            'expiration_secs': int(os.environ.get('AZURE_MEDIA_SAS_SECS', '3600')),  # URLs firmadas
            'overwrite_files': False,
        },
    }

# --- Base de datos: Azure PostgreSQL. Sin password hardcodeado. ---
# Se admite la connection string que inyecta Azure ("dbname=... host=... user=... password=..."),
# o si no, las DB_* de settings.py (que ya traen CONN_MAX_AGE / health checks / connect_timeout).
_conn = os.environ.get('AZURE_POSTGRESQL_CONNECTIONSTRING')
if _conn:
    _p = dict(pair.split('=', 1) for pair in _conn.split(' ') if '=' in pair)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': _p['dbname'],
            'HOST': _p['host'],
            'PORT': _p.get('port', '5432'),
            'USER': _p['user'],
            'PASSWORD': _p['password'],
            'CONN_MAX_AGE': 60,
            'CONN_HEALTH_CHECKS': True,
            'OPTIONS': {'sslmode': _p.get('sslmode', 'require'), 'connect_timeout': 5},
        }
    }
else:
    # Reutiliza DATABASES de settings.py, forzando SSL (obligatorio en Azure PG).
    DATABASES['default'].setdefault('OPTIONS', {})['sslmode'] = 'require'
