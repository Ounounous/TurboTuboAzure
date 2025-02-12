import os
from .settings import *
from .settings import BASE_DIR

# Access the SECRET_KEY securely from environment variables
try:
    SECRET_KEY = os.environ['SECRET']
except KeyError:
    raise Exception(
        "The 'SECRET' environment variable is missing. Please set it in your Azure App Service or deployment pipeline.")

# Ensure WEBSITE_HOSTNAME is set for ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS
try:
    WEBSITE_HOSTNAME = os.environ['WEBSITE_HOSTNAME']
except KeyError:
    # Provide a fallback hostname for local development
    WEBSITE_HOSTNAME = 'localhost'

ALLOWED_HOSTS = [WEBSITE_HOSTNAME]
CSRF_TRUSTED_ORIGINS = ['https://' + WEBSITE_HOSTNAME]

# Disable DEBUG for production
DEBUG = False

# Middleware configuration with Whitenoise for static file serving
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Static files setup for production
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Parse AZURE_POSTGRESQL_CONNECTIONSTRING securely with error handling
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

# Parse the connection string into parameters
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