#!/usr/bin/env bash
# Comando de arranque del App Service (Azure). Configurar en:
#   az webapp config set --startup-file "startup.sh"
# Corre migraciones y levanta gunicorn. collectstatic ya se hizo en el pipeline de deploy.
set -e

python manage.py migrate --noinput

# gthread en vez de workers sync: como el trabajo es I/O (la mayor parte del tiempo un request
# espera a la base de datos), los threads permiten atender muchos mas requests en paralelo sin
# gastar mas CPU -- asi una descarga pesada deja de congelar a los demas usuarios. workers/threads
# se ajustan por env segun el tier del plan, sin tocar codigo. --max-requests recicla el worker
# cada tanto para evitar que la memoria crezca sin techo en un proceso de larga vida.
exec gunicorn turbotubo.wsgi:application \
    --bind=0.0.0.0:8000 \
    --workers=${GUNICORN_WORKERS:-2} \
    --threads=${GUNICORN_THREADS:-4} \
    --worker-class=gthread \
    --timeout=120 \
    --max-requests=1000 \
    --max-requests-jitter=100
