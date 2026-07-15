import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'turbotubo.settings')

app = Celery('turbotubo')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
