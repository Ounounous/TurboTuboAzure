#!/usr/bin/env bash
# Comando de arranque del App Service WORKER (Celery worker + beat). Mismo codigo que la web,
# distinto arranque. Configurar una vez en el App Service worker:
#   az webapp config set -g <RG> -n turbotubo-worker --startup-file "startup-worker.sh"
#
# NO corre gunicorn ni sirve HTTP: este App Service solo procesa tareas de fondo. La web las
# encola via Redis (CELERY_BROKER_URL) y este proceso las ejecuta.
set -e

# ffmpeg: necesario para comprimir las grabaciones a Opus (actions/audio_compress.py). Si no se
# puede instalar, la app cae al fallback y guarda el MP3 sin comprimir -- no rompe nada.
if ! command -v ffmpeg >/dev/null 2>&1; then
    apt-get update && apt-get install -y --no-install-recommends ffmpeg || true
fi

# Worker en segundo plano + beat en primer plano (exec). El beat usa el DatabaseScheduler ya
# fijado en settings (CELERY_BEAT_SCHEDULER), asi lee las tareas de /admin -> Periodic Tasks.
celery -A turbotubo worker --loglevel=info --concurrency=2 &
exec celery -A turbotubo beat --loglevel=info
