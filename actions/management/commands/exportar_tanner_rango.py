"""
Exporta a disco los reportes Tanner de un rango de fechas: un .txt por dia (con el nombre oficial
que exige el instructivo) mas un consolidado con todos los dias juntos.

Es la version por linea de comandos de lo que hace la pantalla "Reportes Tanner por rango" -- usa
exactamente el mismo generador (actions/tanner_report.py), asi que el contenido es identico.

Ejemplo:
    manage.py exportar_tanner_rango --desde 2026-06-01 --hasta 2026-07-31 --salida "C:/ruta/carpeta"
"""
import datetime
import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

from actions.tanner_report import contenido_del_dia, nombre_archivo


class Command(BaseCommand):
    help = "Exporta los reportes Tanner de un rango de fechas: un .txt por dia + un consolidado."

    def add_arguments(self, parser):
        parser.add_argument('--desde', required=True, help='Fecha inicial YYYY-MM-DD.')
        parser.add_argument('--hasta', required=True, help='Fecha final YYYY-MM-DD (inclusive).')
        parser.add_argument('--salida', required=True, help='Carpeta donde dejar los archivos.')
        parser.add_argument(
            '--usuario',
            help='Usuario cuyo alcance se aplica. Por defecto usa un admin/owner (reporte oficial completo).',
        )

    def handle(self, *args, **opts):
        desde, hasta = parse_date(opts['desde']), parse_date(opts['hasta'])
        if not desde or not hasta:
            raise CommandError('--desde y --hasta deben ser fechas YYYY-MM-DD.')
        if desde > hasta:
            raise CommandError('--desde no puede ser posterior a --hasta.')

        if opts.get('usuario'):
            user = User.objects.filter(username=opts['usuario']).first()
            if not user:
                raise CommandError(f"No existe el usuario '{opts['usuario']}'.")
        else:
            # Sin subcartera y con un admin/owner => reporte oficial de toda la cartera Tanner.
            user = User.objects.filter(userprofile__user_type__in=('admin', 'owner')).first()
            if not user:
                raise CommandError('No hay ningun usuario admin/owner para generar el reporte oficial.')

        salida = opts['salida']
        os.makedirs(salida, exist_ok=True)

        consolidado = []
        total = dias_con_datos = 0
        fecha = desde
        while fecha <= hasta:
            contenido, cantidad = contenido_del_dia(fecha, user)
            if cantidad:
                ruta = os.path.join(salida, nombre_archivo(fecha))
                # newline='' para no convertir el \r\n del formato en \r\r\n en Windows.
                with open(ruta, 'w', encoding='utf-8', newline='') as f:
                    f.write(contenido)
                consolidado.append(contenido)
                total += cantidad
                dias_con_datos += 1
                self.stdout.write(f"  {nombre_archivo(fecha)}  ->  {cantidad} gestion(es)")
            fecha += datetime.timedelta(days=1)

        if not consolidado:
            self.stdout.write(self.style.WARNING('No hay gestiones de Tanner en ese rango.'))
            return

        nombre_cons = f"CONSOLIDADO_{desde:%Y%m%d}_a_{hasta:%Y%m%d}.txt"
        with open(os.path.join(salida, nombre_cons), 'w', encoding='utf-8', newline='') as f:
            f.write(''.join(consolidado))

        self.stdout.write(self.style.SUCCESS(
            f"\nListo: {total} gestion(es) en {dias_con_datos} dia(s) con datos.\n"
            f"Archivos en: {salida}\n"
            f"Consolidado: {nombre_cons}"
        ))
