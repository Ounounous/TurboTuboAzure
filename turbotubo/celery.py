import os

from celery import Celery

# Mismo auto-detect que turbotubo/wsgi.py: sin esto, el worker en Azure (WEBSITE_HOSTNAME
# presente) arrancaba con la config de desarrollo -- sin Blob Storage forzado ni endurecimiento
# de produccion -- porque este modulo se importa antes que wsgi.py en el proceso del worker.
settings_module = 'turbotubo.deployment' if 'WEBSITE_HOSTNAME' in os.environ else 'turbotubo.settings'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', settings_module)

app = Celery('turbotubo')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
