"""
Carga el arbol de gestiones de Nuevo Capital parseando su "Paleta Respuestas" (.xlsx).

A diferencia de Tanner (que trae tablas de codigos en un instructivo Word), Nuevo Capital
entrega un Excel con una fila por combinacion valida de:
  Accion (col C) | Sub Estado (col D) | Estado (col E) | In/Out Bound (col G)

La logica de parseo vive en actions/arbol_templates.py (compartida con la asignacion de
arbol desde la web, Carteras -> detalle).
"""
from django.core.management.base import BaseCommand, CommandError

from actions.arbol_templates import importar_nuevo_capital_excel
from cartera.models import Cartera


class Command(BaseCommand):
    help = (
        "Reimporta el arbol de gestiones de Nuevo Capital desde su Paleta Respuestas (.xlsx). "
        "Uso puntual: la asignacion de arbol desde la web (Carteras -> detalle) usa el arbol de "
        "Nuevo Capital ya fijo, sin Excel -- ver actions/arbol_templates.py."
    )

    def add_arguments(self, parser):
        parser.add_argument('excel_path')

    def handle(self, *args, **options):
        try:
            cartera = Cartera.objects.get(nombre__iexact='Nuevo Capital')
        except Cartera.DoesNotExist:
            raise CommandError("No existe la cartera 'Nuevo Capital'. Creala primero en /dashboard/carteras/.")

        stats = importar_nuevo_capital_excel(cartera, options['excel_path'])

        self.stdout.write(self.style.SUCCESS(
            f"Cartera 'Nuevo Capital': {stats['medios_creados']} medio(s) nuevo(s), "
            f"{stats['resultados_creados']} resultado(s) nuevo(s), {stats['resultados_actualizados']} actualizado(s)."
        ))
