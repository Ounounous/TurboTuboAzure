#!/usr/bin/env bash
# Comando de arranque del App Service (Azure). Configurar en:
#   az webapp config set --startup-file "startup.sh"
# Corre migraciones y levanta gunicorn. collectstatic ya se hizo en el pipeline de deploy.
set -e

python manage.py migrate --noinput

# 3 workers, timeout amplio para descargas/reportes Excel grandes.
exec gunicorn turbotubo.wsgi:application \
    --bind=0.0.0.0:8000 \
    --workers=3 \
    --timeout=120
