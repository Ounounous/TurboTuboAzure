from django.core.management.base import BaseCommand, CommandError

from actions.arbol_templates import importar_galgo_excel
from cartera.models import Cartera


class Command(BaseCommand):
    help = (
        "Importa el arbol de gestiones (medios y resultados) de una cartera desde un Excel "
        "con columnas: Medio de contacto, Estado del contacto, Contactabilidad, DEFAULT, CREA COMPROMISO. "
        "Los datos empiezan en la fila 3 (las 2 primeras son encabezados). Medio y Resultado se "
        "guardan como catalogos independientes de la cartera (un mismo resultado puede repetirse "
        "bajo varios medios en el Excel de origen -- se deduplica por nombre). Uso puntual: la "
        "asignacion de arbol desde la web (Carteras -> detalle) usa el arbol de Galgo ya fijo, "
        "sin Excel -- ver actions/arbol_templates.py."
    )

    def add_arguments(self, parser):
        parser.add_argument('cartera_nombre')
        parser.add_argument('excel_path')

    def handle(self, *args, **options):
        cartera_nombre = options['cartera_nombre']
        excel_path = options['excel_path']

        try:
            cartera = Cartera.objects.get(nombre__iexact=cartera_nombre)
        except Cartera.DoesNotExist:
            raise CommandError(f"No existe la cartera '{cartera_nombre}'. Creala primero en /dashboard/carteras/.")

        stats = importar_galgo_excel(cartera, excel_path)

        self.stdout.write(self.style.SUCCESS(
            f"Cartera '{cartera.nombre}': {stats['medios_creados']} medio(s) nuevo(s), "
            f"{stats['resultados_creados']} resultado(s) nuevo(s), {stats['resultados_actualizados']} actualizado(s), "
            f"{stats['filas_omitidas']} fila(s) omitida(s)."
        ))
