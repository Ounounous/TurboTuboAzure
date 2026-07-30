"""
Carga el arbol de gestiones de Tanner. A diferencia de Galgo, Tanner no entrega un Excel
con columnas Medio/Resultado/Contactabilidad -- el "Instructivo base de gestiones - Tanner
Automotriz (version 11)" define dos tablas de codigos independientes (medio 1-8, respuestas
100-800). Los datos estan transcritos en actions/arbol_templates.py (compartido con la
asignacion de arbol desde la web, Carteras -> detalle), este comando no necesita argumentos.
"""
from django.core.management.base import BaseCommand, CommandError

from actions.arbol_templates import aplicar_tanner
from cartera.models import Cartera


class Command(BaseCommand):
    help = "Carga el arbol de gestiones de Tanner (medios y resultados transcritos del instructivo oficial)."

    def handle(self, *args, **options):
        try:
            cartera = Cartera.objects.get(nombre__iexact='Tanner')
        except Cartera.DoesNotExist:
            raise CommandError("No existe la cartera 'Tanner'. Creala primero en /dashboard/carteras/.")

        stats = aplicar_tanner(cartera)

        self.stdout.write(self.style.SUCCESS(
            f"Cartera 'Tanner': {stats['medios_creados']} medio(s) nuevo(s), "
            f"{stats['resultados_creados']} resultado(s) nuevo(s), {stats['resultados_actualizados']} actualizado(s)."
        ))
