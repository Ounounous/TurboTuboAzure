"""
Siembra MapeoResultadoCampana para Galgo, tal como está transcrito en CONTRATO_API_v1.md
sección 3.1. Fase 4 solo habilita Galgo (ver api/tasks.py::CARTERAS_ARBOL_HABILITADO) -- Tanner
y Nuevo Capital se siembran en su propio comando cuando se habiliten (Fase 5+).

Idempotente (update_or_create). Requiere que la cartera ya tenga el árbol Galgo aplicado
(Cartera.arbol_tipo == 'galgo') -- si no, CommandError explícito.
"""
from django.core.management.base import BaseCommand, CommandError

from actions.models import Medio, Resultado
from api.models import MapeoResultadoCampana
from cartera.models import Cartera

# (canal, resultado_corto, nombre_medio, nombre_resultado) -- exactamente la tabla de
# CONTRATO_API_v1.md sección 3.1. Las filas "cualquiera" del contrato se expanden aquí a una fila
# por canal, porque MapeoResultadoCampana es (cartera, canal, resultado_corto) único.
FILAS = [
    ('email', 'entregado', 'EMAIL', 'MSJ DE CONTACTO'),
    ('email', 'no_entregado', 'EMAIL', 'EMAIL INVALIDO'),
    ('whatsapp', 'entregado', 'WHATSAPP', 'MSJ DE CONTACTO'),
    ('whatsapp', 'no_entregado', 'WHATSAPP', 'MSJ DE CONTACTO'),
    ('whatsapp', 'sin_whatsapp', 'WHATSAPP', 'SIN WHATSAPP'),
    ('sms', 'entregado', 'WHATSAPP', 'MSJ DE CONTACTO'),
    ('sms', 'no_entregado', 'WHATSAPP', 'FONO NO CORRESPONDE'),
    # "cualquiera" del contrato -> una fila por cada canal que existe en Galgo.
    ('email', 'sin_respuesta', 'EMAIL', 'NO RESPONDE'),
    ('whatsapp', 'sin_respuesta', 'WHATSAPP', 'NO RESPONDE'),
    ('sms', 'sin_respuesta', 'WHATSAPP', 'NO RESPONDE'),
    ('email', 'humano_detectado', 'EMAIL', 'MSJ DE CONTACTO'),
    ('whatsapp', 'humano_detectado', 'WHATSAPP', 'MSJ DE CONTACTO'),
    ('sms', 'humano_detectado', 'WHATSAPP', 'MSJ DE CONTACTO'),
    ('email', 'buzon_detectado', 'EMAIL', 'NO RESPONDE'),
    ('whatsapp', 'buzon_detectado', 'WHATSAPP', 'NO RESPONDE'),
    ('sms', 'buzon_detectado', 'WHATSAPP', 'NO RESPONDE'),
    ('email', 'error_conexion', 'EMAIL', 'NO RESPONDE'),
    ('whatsapp', 'error_conexion', 'WHATSAPP', 'NO RESPONDE'),
    ('sms', 'error_conexion', 'WHATSAPP', 'NO RESPONDE'),
    ('email', 'no_disponible', 'EMAIL', 'NO RESPONDE'),
    ('whatsapp', 'no_disponible', 'WHATSAPP', 'NO RESPONDE'),
    ('sms', 'no_disponible', 'WHATSAPP', 'NO RESPONDE'),
]


class Command(BaseCommand):
    help = 'Siembra MapeoResultadoCampana para Galgo según CONTRATO_API_v1.md sección 3.1.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--cartera', default='Galgo',
            help="Nombre exacto de la cartera (por defecto 'Galgo'; útil para sembrar sobre 'Galgo DEMO' en pruebas).",
        )

    def handle(self, *args, **options):
        nombre_cartera = options['cartera']
        try:
            cartera = Cartera.objects.get(nombre__iexact=nombre_cartera)
        except Cartera.DoesNotExist:
            raise CommandError(f"No existe la cartera '{nombre_cartera}'.")
        if cartera.arbol_tipo != Cartera.ARBOL_GALGO:
            raise CommandError(
                f"La cartera '{nombre_cartera}' no tiene el árbol Galgo aplicado (arbol_tipo={cartera.arbol_tipo!r}). "
                "Asígnalo desde Carteras -> detalle antes de sembrar el mapeo."
            )

        creados = actualizados = 0
        for canal, resultado_corto, nombre_medio, nombre_resultado in FILAS:
            try:
                medio = Medio.objects.get(cartera=cartera, nombre=nombre_medio)
                resultado = Resultado.objects.get(cartera=cartera, nombre=nombre_resultado)
            except (Medio.DoesNotExist, Resultado.DoesNotExist) as exc:
                raise CommandError(f'No se encontró Medio/Resultado para la fila {(canal, resultado_corto)}: {exc}')

            _, created = MapeoResultadoCampana.objects.update_or_create(
                cartera=cartera, canal=canal, resultado_corto=resultado_corto,
                defaults={'medio': medio, 'resultado': resultado},
            )
            creados += int(created)
            actualizados += int(not created)

        self.stdout.write(self.style.SUCCESS(
            f"Cartera '{nombre_cartera}': {creados} mapeo(s) nuevo(s), {actualizados} actualizado(s)."
        ))
