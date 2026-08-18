"""
Siembra MapeoResultadoCampana para Tanner, tal como está transcrito en CONTRATO_API_v1.md
sección 3.2 -- los 11 códigos ACCION MASIVA (600-610), medio fijo "Bot" (código 8).

Precaución obligatoria nº1 del plan de riesgos ("Nunca aceptar resultado por nombre libre"):
busca el Resultado por (cartera, codigo, tipo_contacto), nunca por nombre -- "OTROS" existe en
124 (DIRECTO) y en 222 (DIRECTO AVAL), un nombre suelto es ambiguo.

Precaución obligatoria nº2 ("Rechazar los códigos 129-153"): CommandError explícito si alguna fila
de FILAS apuntara a un código en TANNER_CODIGOS_NO_MANUAL -- no debería pasar nunca (129-153 son
todos tipo_contacto=DIRECTO, fuera del rango 600-610 de ACCION MASIVA), pero se verifica en código,
no solo "por diseño", antes de sembrar cualquier fila.

Idempotente (update_or_create). Requiere que la cartera ya tenga el árbol Tanner aplicado.
"""
from django.core.management.base import BaseCommand, CommandError

from actions.arbol_templates import TANNER_CODIGOS_NO_MANUAL
from actions.models import Medio, Resultado
from api.models import MapeoResultadoCampana
from cartera.models import Cartera

# (canal, resultado_corto, codigo_tanner) -- exactamente CONTRATO_API_v1.md sección 3.2. Todos
# tipo_contacto='ACCION MASIVA', medio='Bot' (código 8, ver TANNER_MEDIOS en arbol_templates.py).
FILAS = [
    ('sms', 'entregado', '600'),
    ('sms', 'no_entregado', '605'),
    ('carta', 'entregado', '601'),
    ('carta', 'no_entregado', '606'),
    ('email', 'entregado', '602'),
    ('email', 'no_entregado', '607'),
    ('whatsapp', 'entregado', '603'),
    ('whatsapp', 'no_entregado', '608'),
    ('whatsapp', 'sin_whatsapp', '608'),
    ('ivr', 'humano_detectado', '604'),
    ('ivr', 'entregado', '604'),
    ('ivr', 'buzon_detectado', '609'),
    ('ivr', 'sin_respuesta', '610'),
    ('ivr', 'no_entregado', '610'),
    ('ivr', 'error_conexion', '610'),
    ('ivr', 'no_disponible', '610'),
]

TIPO_CONTACTO = 'ACCION MASIVA'
NOMBRE_MEDIO = 'Bot'


class Command(BaseCommand):
    help = 'Siembra MapeoResultadoCampana para Tanner según CONTRATO_API_v1.md sección 3.2.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--cartera', default='Tanner',
            help="Nombre exacto de la cartera (por defecto 'Tanner'; útil para sembrar sobre 'Tanner DEMO' en pruebas).",
        )

    def handle(self, *args, **options):
        nombre_cartera = options['cartera']
        try:
            cartera = Cartera.objects.get(nombre__iexact=nombre_cartera)
        except Cartera.DoesNotExist:
            raise CommandError(f"No existe la cartera '{nombre_cartera}'.")
        if cartera.arbol_tipo != Cartera.ARBOL_TANNER:
            raise CommandError(
                f"La cartera '{nombre_cartera}' no tiene el árbol Tanner aplicado (arbol_tipo={cartera.arbol_tipo!r}). "
                "Asígnalo desde Carteras -> detalle antes de sembrar el mapeo."
            )

        # Precaución nº2, verificada en código antes de tocar la base: ninguna fila puede
        # apuntar a un código bloqueado (129-153, PAC/venta directa).
        codigos_en_filas = {codigo for _, _, codigo in FILAS}
        bloqueados = codigos_en_filas & TANNER_CODIGOS_NO_MANUAL
        if bloqueados:
            raise CommandError(
                f'FILAS contiene código(s) bloqueado(s) (TANNER_CODIGOS_NO_MANUAL): {sorted(bloqueados)}. '
                'Esto no debería pasar nunca -- revisa el archivo antes de sembrar.'
            )

        try:
            medio = Medio.objects.get(cartera=cartera, nombre=NOMBRE_MEDIO)
        except Medio.DoesNotExist:
            raise CommandError(f"No se encontró el Medio '{NOMBRE_MEDIO}' en la cartera '{nombre_cartera}'.")

        creados = actualizados = 0
        for canal, resultado_corto, codigo in FILAS:
            # Precaución nº1: busca SIEMPRE por (cartera, codigo, tipo_contacto), nunca por nombre.
            try:
                resultado = Resultado.objects.get(cartera=cartera, codigo=codigo, tipo_contacto=TIPO_CONTACTO)
            except Resultado.DoesNotExist:
                raise CommandError(
                    f"No se encontró Resultado con codigo='{codigo}' tipo_contacto='{TIPO_CONTACTO}' "
                    f"en la cartera '{nombre_cartera}'."
                )
            if resultado.codigo in TANNER_CODIGOS_NO_MANUAL:
                # Defensivo: no debería poder pasar (ver check de arriba), pero si algún día FILAS
                # se edita mal, esto es la última barrera antes de escribir en la base.
                raise CommandError(f'Resultado {resultado} tiene código bloqueado {resultado.codigo!r}.')

            _, created = MapeoResultadoCampana.objects.update_or_create(
                cartera=cartera, canal=canal, resultado_corto=resultado_corto,
                defaults={'medio': medio, 'resultado': resultado},
            )
            creados += int(created)
            actualizados += int(not created)

        self.stdout.write(self.style.SUCCESS(
            f"Cartera '{nombre_cartera}': {creados} mapeo(s) nuevo(s), {actualizados} actualizado(s)."
        ))
