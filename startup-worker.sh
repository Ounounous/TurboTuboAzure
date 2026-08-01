#!/usr/bin/env bash
# Comando de arranque del App Service WORKER (Celery worker + beat). Mismo codigo que la web,
# distinto arranque. Configurar una vez en el App Service worker:
#   az webapp config set -g <RG> -n turbotubo-worker --startup-file "startup-worker.sh"
#
# NO corre gunicorn: este App Service solo procesa tareas de fondo. La web las encola via Redis
# (CELERY_BROKER_URL) y este proceso las ejecuta.
set -e

# Sonda HTTP (worker_probe.py): Azure App Service mata cualquier contenedor que no escuche en un
# puerto ("No listening ports were detected", 230s de gracia) y lo reinicia en bucle. Celery no
# sirve HTTP, asi que sin esto el worker vivia ~4 minutos por arranque -- se detectaron 28
# reinicios y las tareas quedaban encoladas sin procesar. Este servidor minimo responde 200 y
# mantiene el contenedor vivo.
python worker_probe.py &

# ffmpeg: necesario para comprimir las grabaciones a Opus (actions/audio_compress.py). Si no se
# puede instalar, la app cae al fallback y guarda el MP3 sin comprimir -- no rompe nada.
if ! command -v ffmpeg >/dev/null 2>&1; then
    apt-get update && apt-get install -y --no-install-recommends ffmpeg || true
fi

# Worker en segundo plano + beat en primer plano (exec). El beat usa el DatabaseScheduler ya
# fijado en settings (CELERY_BEAT_SCHEDULER), asi lee las tareas de /admin -> Periodic Tasks.
celery -A turbotubo worker --loglevel=info --concurrency=2 &
exec celery -A turbotubo beat --loglevel=info
