import os
from .settings import *
from .settings import BASE_DIR

# ACCESS SECRET_KEY SECURELY
try:
    SECRET_KEY = os.environ['SECRET']
except KeyError:
    raise Exception(
        "The 'SECRET' environment variable is missing. Please set it in your Azure App Service or deployment pipeline."
    )

# ACCESS WEBSITE_HOSTNAME FOR ALLOWED_HOSTS AND CSRF_TRUSTED_ORIGINS
try:
    WEBSITE_HOSTNAME = os.environ['WEBSITE_HOSTNAME']  # Azure provides this automatically
except KeyError:
    WEBSITE_HOSTNAME = 'localhost'  # Fallback for local testing

ALLOWED_HOSTS = [WEBSITE_HOSTNAME]
CSRF_TRUSTED_ORIGINS = ['https://' + WEBSITE_HOSTNAME]

# DISABLE DEBUG FOR PRODUCTION
DEBUG = True

# HTTPS SECURITY SETTINGS
SECURE_SSL_REDIRECT = True  # Redirect all HTTP traffic to HTTPS
SESSION_COOKIE_SECURE = True  # Ensure cookies are sent over HTTPS only
CSRF_COOKIE_SECURE = True  # Protect CSRF cookies via HTTPS
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')  # Identify HTTPS requests via proxy

# ENABLE HTTP STRICT TRANSPORT SECURITY (HSTS)
SECURE_HSTS_SECONDS = 31536000  # Enforce HTTPS for 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True  # Apply to subdomains
SECURE_HSTS_PRELOAD = True  # Preload HSTS in browsers
# Note: SECURE_HSTS_PRELOAD is safe to enable, as your app is already using HTTPS.

# MIDDLEWARE FOR STATIC FILE SERVING WITH WHITENOISE
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Enables serving static files efficiently via Whitenoise
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# STATIC FILES CONFIGURATION FOR PRODUCTION
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# DATABASE CONFIGURATION FROM AZURE CONNECTION STRING
try:
    # Try to load the connection string from the environment variables
    connection_string = os.environ['AZURE_POSTGRESQL_CONNECTIONSTRING']
except KeyError:
    # Provide a fallback for local development
    connection_string = (
        "dbname=turbotubobeta-database "
        "host=turbotubobeta-server.postgres.database.azure.com "
        "port=5432 "
        "sslmode=require "
        "user=jpkbqsuzen "
        "password=Dt0ylE4wKt$bIMo3"
    )

# PARSE THE CONNECTION STRING INTO PARAMETERS
try:
    parameters = {
        pair.split('=')[0]: pair.split('=')[1]
        for pair in connection_string.split(' ')
    }

    # Prepare DATABASES settings for the Django app
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': parameters['dbname'],
            'HOST': parameters['host'],
            'PORT': parameters.get('port', 5432),  # Default to port 5432
            'USER': parameters['user'],
            'PASSWORD': parameters['password'],
            'OPTIONS': {
                'sslmode': parameters.get('sslmode', 'require')  # Default SSL mode to "require"
            },
        }
    }
except KeyError as e:
    raise Exception(f"Missing or malformed connection string. Error parsing key: {e}")
except Exception as e:
    raise Exception(f"An error occurred while parsing the connection string: {e}")