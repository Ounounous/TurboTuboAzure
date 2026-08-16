"""
Freno de efectos demográficos en cascada (plan de riesgos, sección 04 "Efecto demográfico en
cascada"): un motor de campañas mal calibrado que reporte rebotes en masa puede apagar miles de
datos de contacto de un golpe (Resultado.efecto_demografia -> Phone.phone_number_status /
IDDemographics.principal_email_status, aplicado en actions/status_logic.py::aplicar_efecto_demografico,
dentro de Action.save()).

No se reimplementa esa lógica -- se cuenta, ANTES de crear el Action, cuántos efectos demográficos
ya se aplicaron vía webhook para este cliente en la ventana reciente. Si el umbral se supera, el
evento actual queda DETENIDO_FRENO sin crear el Action, y se registra la alerta (log + AccessLog;
ver decisión de diseño: sin canal de email/Slack todavía, se agrega después sin tocar esta lógica).
"""
import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Defaults si no están en settings -- deliberadamente bajos: Galgo es la única cartera habilitada
# en Fase 4 y el volumen esperado por lote es chico.
_DEFAULT_UMBRAL = 50
_DEFAULT_VENTANA_MINUTOS = 10


def _umbral():
    # Leído en cada llamada (no a nivel de módulo): un valor fijado al importar no respondería a
    # override_settings en tests ni a un cambio de settings en runtime.
    return getattr(settings, 'WEBHOOK_FRENO_DEMOGRAFICO_UMBRAL', _DEFAULT_UMBRAL)


def _ventana_minutos():
    return getattr(settings, 'WEBHOOK_FRENO_DEMOGRAFICO_VENTANA_MINUTOS', _DEFAULT_VENTANA_MINUTOS)


def efectos_recientes(cliente):
    """Cuenta WebhookEventoJob APLICADO de este cliente, en la ventana, cuyo Action tiene un
    Resultado con efecto_demografia configurado -- el mismo criterio que aplicar_efecto_demografico
    usa para decidir si hay algo que apagar."""
    from .models import WebhookEventoJob

    desde = timezone.now() - timezone.timedelta(minutes=_ventana_minutos())
    return WebhookEventoJob.objects.filter(
        cliente=cliente, estado=WebhookEventoJob.APLICADO, created_at__gte=desde,
        action__resultado__efecto_demografia__gt='',
    ).count()


def verificar_freno(cliente, resultado):
    """True si procesar este evento (dado su Resultado) superaría el umbral -- en cuyo caso el
    caller NO debe crear el Action. No es un "esto se aplicó y se revierte" -- es un "no ejecutar
    si ya estamos en el límite", para no tener que deshacer un efecto demográfico ya aplicado."""
    if not resultado.efecto_demografia:
        return False  # este resultado en particular no toca demografía, no cuenta para el freno

    umbral = _umbral()
    n = efectos_recientes(cliente)
    if n < umbral:
        return False

    ventana = _ventana_minutos()
    logger.error(
        f'freno_demografico: cliente "{cliente.nombre}" alcanzó {n} efectos demográficos vía '
        f'webhook en los últimos {ventana} min (umbral {umbral}) -- se detiene el procesamiento '
        f'de nuevos eventos de este cliente hasta que la ventana pase.'
    )
    from configuracion.models import AccessLog, registrar_acceso
    registrar_acceso(
        None, AccessLog.FRENO_DEMOGRAFICO_WEBHOOK, detail=(
            f'Cliente API "{cliente.nombre}" — {n} efectos en {ventana} min, umbral {umbral}'
        )[:255],
    )
    return True
