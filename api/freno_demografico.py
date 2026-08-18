"""
Frenos de contención para el webhook de escritura (plan de riesgos, sección 04 "Efecto
demográfico en cascada" + hallazgo 2 de la auditoría de riesgos): un motor de campañas mal
calibrado que reporte rebotes en masa puede apagar miles de datos de contacto de un golpe
(Resultado.efecto_demografia -> Phone.phone_number_status / IDDemographics.principal_email_status,
aplicado en actions/status_logic.py::aplicar_efecto_demografico, dentro de Action.save()).

Dos frenos independientes, ambos evaluados antes de crear el Action:

- verificar_freno(): cuenta efectos demográficos REALES ya aplicados (requiere que el Action
  lleve phone/email -- ver api/tasks.py::_resolver_contacto, agregado junto con este freno; antes
  el Action del webhook no llevaba ninguno de los dos y este freno nunca podía dispararse).
- verificar_freno_volumen(): cuenta CUALQUIER evento aplicado por el cliente en la ventana, sin
  importar si tocó demografía. Cubre el caso de una descalibración masiva sobre resultados que no
  tienen efecto_demografia configurado (ej. hoy ningún mapeo Tanner/Galgo lo tiene) -- sin este
  segundo freno, un motor descalibrado podía crear decenas de miles de Action reales sin que nada
  lo detuviera, aunque ninguno tocara un teléfono/correo.

No se reimplementa la lógica de aplicar_efecto_demografico -- se cuenta, ANTES de crear el
Action, cuánto se aplicó vía webhook para este cliente en la ventana reciente. Si el umbral se
supera, el evento actual queda DETENIDO_FRENO sin crear el Action, y se registra la alerta (log +
AccessLog; sin canal de email/Slack todavía, se agrega después sin tocar esta lógica).
"""
import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Defaults si no están en settings -- deliberadamente bajos: Galgo y Tanner son las únicas
# carteras habilitadas y el volumen esperado por lote es chico.
_DEFAULT_UMBRAL_DEMOGRAFICO = 50
_DEFAULT_UMBRAL_VOLUMEN = 200
_DEFAULT_VENTANA_MINUTOS = 10


def _umbral_demografico():
    # Leído en cada llamada (no a nivel de módulo): un valor fijado al importar no respondería a
    # override_settings en tests ni a un cambio de settings en runtime.
    return getattr(settings, 'WEBHOOK_FRENO_DEMOGRAFICO_UMBRAL', _DEFAULT_UMBRAL_DEMOGRAFICO)


def _umbral_volumen():
    return getattr(settings, 'WEBHOOK_FRENO_VOLUMEN_UMBRAL', _DEFAULT_UMBRAL_VOLUMEN)


def _ventana_minutos():
    return getattr(settings, 'WEBHOOK_FRENO_DEMOGRAFICO_VENTANA_MINUTOS', _DEFAULT_VENTANA_MINUTOS)


def _registrar_alerta(cliente, n, umbral, ventana, motivo):
    logger.error(
        f'freno_demografico: cliente "{cliente.nombre}" alcanzó {n} en los últimos {ventana} min '
        f'(umbral {umbral}, {motivo}) -- se detiene el procesamiento de nuevos eventos de este '
        f'cliente hasta que la ventana pase.'
    )
    from configuracion.models import AccessLog, registrar_acceso
    registrar_acceso(
        None, AccessLog.FRENO_DEMOGRAFICO_WEBHOOK, detail=(
            f'Cliente API "{cliente.nombre}" — {n} en {ventana} min, umbral {umbral} ({motivo})'
        )[:255],
    )


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


def eventos_recientes(cliente):
    """Cuenta CUALQUIER WebhookEventoJob APLICADO de este cliente en la ventana, sin filtrar por
    efecto_demografia -- base del freno de volumen."""
    from .models import WebhookEventoJob

    desde = timezone.now() - timezone.timedelta(minutes=_ventana_minutos())
    return WebhookEventoJob.objects.filter(
        cliente=cliente, estado=WebhookEventoJob.APLICADO, created_at__gte=desde,
    ).count()


def verificar_freno(cliente, resultado):
    """(bool, motivo). True si procesar este evento (dado su Resultado) superaría el umbral
    demográfico -- en cuyo caso el caller NO debe crear el Action. No es un "esto se aplicó y se
    revierte" -- es un "no ejecutar si ya estamos en el límite", para no tener que deshacer un
    efecto demográfico ya aplicado."""
    if not resultado.efecto_demografia:
        return False, ''  # este resultado en particular no toca demografía, no cuenta para el freno

    umbral = _umbral_demografico()
    n = efectos_recientes(cliente)
    if n < umbral:
        return False, ''

    motivo = 'efectos demográficos'
    _registrar_alerta(cliente, n, umbral, _ventana_minutos(), motivo)
    return True, motivo


def verificar_freno_volumen(cliente):
    """(bool, motivo). True si el cliente ya superó el umbral de eventos APLICADOS en la ventana,
    sin importar si tocaron demografía -- protege contra una descalibración masiva del motor
    externo incluso cuando el resultado en cuestión no tiene efecto_demografia configurado
    (hoy ningún mapeo Tanner/Galgo lo tiene, ver verificar_freno)."""
    umbral = _umbral_volumen()
    n = eventos_recientes(cliente)
    if n < umbral:
        return False, ''

    motivo = 'volumen de eventos'
    _registrar_alerta(cliente, n, umbral, _ventana_minutos(), motivo)
    return True, motivo
