"""
Crea 3 carteras de PRUEBA (Galgo/Tanner/Nuevo Capital) clonando sus medios y resultados de las
carteras reales, con leads de prueba que cubren los escenarios de demografia/status, y genera
los Excel de demografia (telefonos y correos) para cargarlos por la UI y hacer pruebas.

Idempotente: se puede correr varias veces (get_or_create). Para limpiar todo:
    python manage.py crear_carteras_prueba --borrar
"""
import os

import openpyxl
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from actions.models import Medio, Resultado
from cartera.models import Cartera, Subcartera
from lead.models import Lead
from team.models import Team

SUFIJO = ' PRUEBA'
CARTERAS_BASE = ['Galgo', 'Tanner', 'Nuevo Capital']
PREFIJO_OP = {'Galgo': 'GALP', 'Tanner': 'TANP', 'Nuevo Capital': 'NCP'}
OUT_DIR = r"C:\Users\cgonz\Desktop\zona sur\Turbotubo\PRUEBAS demografia"

# Escenarios (uno por lead). phones = [(numero, tipo, estado, whatsapp)]. correo con su estado.
# Estados validos: active | non-existent | out of service | blacklisted.
ESCENARIOS = [
    # op, nombre, telefonos, correo, correo_estado
    ('01', 'Ana Normal',
     [('+56911110001', 'principal', 'active', True)], 'ana@test.cl', 'active'),
    ('02', 'Beto Blacklist',
     [('+56911110002', 'principal', 'blacklisted', True), ('+56911110012', 'principal', 'active', True)],
     'beto@test.cl', 'active'),
    ('03', 'Carla Inubicable',
     [('+56911110003', 'principal', 'non-existent', True)], 'carla@test.cl', 'non-existent'),
    ('04', 'Diego SinWhatsApp',
     [('+56911110004', 'principal', 'active', False)], 'diego@test.cl', 'active'),
    ('05', 'Eva CorreoBlacklist',
     [('+56911110005', 'principal', 'active', True)], 'eva@test.cl', 'blacklisted'),
    ('06', 'Fran FueraServicio',
     [('+56911110006', 'principal', 'out of service', True)], 'fran@test.cl', 'active'),
]

PHONE_HEADERS = ['cartera', 'subcartera', 'op', 'phone_number', 'phone_type', 'phone_status']
EMAIL_HEADERS = ['cartera', 'subcartera', 'op', 'principal_email']
EMAIL_STATUS_HEADERS = ['cartera', 'subcartera', 'op', 'correo', 'estado']
PHONE_STATUS_HEADERS = ['cartera', 'subcartera', 'op', 'telefono', 'estado', 'whatsapp']


class Command(BaseCommand):
    help = 'Crea carteras/leads de prueba y genera los Excel de demografia.'

    def add_arguments(self, parser):
        parser.add_argument('--borrar', action='store_true', help='Elimina las carteras de prueba y sus datos.')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['borrar']:
            return self._borrar()

        user = User.objects.filter(is_superuser=True).first() or User.objects.first()
        if not user:
            raise CommandError('No hay usuarios; crea un superusuario primero.')
        team = getattr(user.userprofile, 'active_team', None) or Team.objects.first()
        if not team:
            raise CommandError('No hay Team; crea uno primero.')

        os.makedirs(OUT_DIR, exist_ok=True)

        for base in CARTERAS_BASE:
            real = Cartera.objects.filter(nombre__iexact=base).first()
            if not real:
                self.stdout.write(self.style.WARNING(f'Cartera real "{base}" no existe, se omite.'))
                continue
            self._crear_cartera_prueba(base, real, team, user)

        self.stdout.write(self.style.SUCCESS(f'Listo. Excel de demografia en:\n  {OUT_DIR}'))

    def _crear_cartera_prueba(self, base, real, team, user):
        nombre = base + SUFIJO
        cartera, _ = Cartera.objects.get_or_create(nombre=nombre, defaults={'created_by': user})
        subcartera = cartera.subcartera_default  # se auto-crea con la cartera (mismo nombre)

        # Clonar medios y resultados de la cartera real (incluye efecto_pago, efecto_demografia,
        # desactiva_whatsapp, contactabilidad, codigos, etc. -- lo ya curado).
        for m in Medio.objects.filter(cartera=real):
            Medio.objects.get_or_create(
                cartera=cartera, nombre=m.nombre,
                defaults={'canal': m.canal, 'es_llamada': m.es_llamada, 'codigo': m.codigo,
                          'es_inbound': m.es_inbound, 'permite_manual': m.permite_manual},
            )
        for r in Resultado.objects.filter(cartera=real):
            Resultado.objects.get_or_create(
                cartera=cartera, nombre=r.nombre, tipo_contacto=r.tipo_contacto,
                defaults={'codigo': r.codigo, 'contactabilidad': r.contactabilidad,
                          'es_default': r.es_default, 'crea_compromiso': r.crea_compromiso,
                          'requiere_fecha_pago': r.requiere_fecha_pago, 'efecto_pago': r.efecto_pago,
                          'efecto_demografia': r.efecto_demografia, 'desactiva_whatsapp': r.desactiva_whatsapp,
                          'descarga_grabacion': r.descarga_grabacion},
            )

        # Leads de prueba (SIN demografia: eso se carga por los Excel para probar el flujo).
        prefijo = PREFIJO_OP[base]
        leads_creados = 0
        for suf, lead_nombre, _tels, _correo, _est in ESCENARIOS:
            op = f'{prefijo}-{suf}'
            _, created = Lead.objects.get_or_create(
                op=op, subcartera=subcartera,
                defaults={
                    'team': team, 'name': lead_nombre, 'rut': 20000000 + int(suf), 'dv': '0',
                    'saldo_insoluto': 1000000, 'saldo_deuda': 1000000, 'valor_cuota': 50000,
                    'cuotas_atrasadas': 2, 'created_by': user, 'assigned_to': user,
                },
            )
            leads_creados += int(created)

        self._escribir_excels(base, cartera.nombre, subcartera.nombre)
        self.stdout.write(self.style.SUCCESS(
            f'{cartera.nombre}: medios/resultados clonados, {leads_creados} lead(s) nuevo(s).'
        ))

    def _escribir_excels(self, base, cartera_nombre, subcartera_nombre):
        prefijo = PREFIJO_OP[base]

        def nuevo(headers):
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(headers)
            return wb, ws

        wb_tel, ws_tel = nuevo(PHONE_HEADERS)
        wb_cor, ws_cor = nuevo(EMAIL_HEADERS)
        wb_est_cor, ws_est_cor = nuevo(EMAIL_STATUS_HEADERS)
        wb_est_tel, ws_est_tel = nuevo(PHONE_STATUS_HEADERS)

        for suf, _nombre, tels, correo, correo_est in ESCENARIOS:
            op = f'{prefijo}-{suf}'
            for numero, tipo, estado, whatsapp in tels:
                # Carga de telefonos con su estado (probar blacklist / inubicable directamente).
                ws_tel.append([cartera_nombre, subcartera_nombre, op, numero, tipo, estado])
                # Bulk de estado de telefonos (para probar whatsapp on/off por Excel).
                ws_est_tel.append([cartera_nombre, subcartera_nombre, op, numero, estado, 'si' if whatsapp else 'no'])
            # Carga de correos (direccion; el estado se setea por el bulk de estado de correos).
            ws_cor.append([cartera_nombre, subcartera_nombre, op, correo])
            ws_est_cor.append([cartera_nombre, subcartera_nombre, op, correo, correo_est])

        wb_tel.save(os.path.join(OUT_DIR, f'telefonos_{base}.xlsx'))
        wb_cor.save(os.path.join(OUT_DIR, f'correos_{base}.xlsx'))
        wb_est_cor.save(os.path.join(OUT_DIR, f'estado_correos_{base}.xlsx'))
        wb_est_tel.save(os.path.join(OUT_DIR, f'estado_telefonos_{base}.xlsx'))

    def _borrar(self):
        nombres = [b + SUFIJO for b in CARTERAS_BASE]
        carteras = Cartera.objects.filter(nombre__in=nombres)
        n = carteras.count()
        # Lead -> Phone/IDDemographics/Action caen por CASCADE; Resultado/Medio por CASCADE de Cartera.
        Lead.objects.filter(subcartera__cartera__in=carteras).delete()
        carteras.delete()
        self.stdout.write(self.style.SUCCESS(f'{n} cartera(s) de prueba eliminada(s).'))
