"""
Puebla una base de datos local vacia con datos de demo multi-cartera (Galgo, Tanner, Nuevo
Capital): equipo + usuarios, las 3 carteras con su arbol de gestiones real (via
actions/arbol_templates.py, igual que la asignacion desde Carteras -> detalle), y un lote de
leads con demografia, gestiones y pagos que recorren los distintos status posibles.

Pensado para el ambiente Docker local (Fase 0): despues de `docker-compose up` + `migrate` +
`createsuperuser`, este comando deja algo navegable sin depender de datos de produccion.

Solo corre con DEBUG=True -- nunca contra una base real.

Idempotente (get_or_create en todo). Para limpiar:
    python manage.py generar_datos_demo --borrar
"""
import datetime
import random

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from actions.arbol_templates import APLICAR_POR_TIPO
from actions.models import Action, Medio, Payment, Resultado
from cartera.models import Cartera, Subcartera
from demographics.models import IDDemographics, Phone
from lead.models import Lead
from team.models import Team

# Nombres propios (no "Galgo"/"Tanner"/"Nuevo Capital" a secas) para no mezclarse jamas con una
# cartera real que ya tenga datos en esta base -- este comando es para una base vacia (Fase 0).
SUFIJO = ' DEMO'
CARTERAS_BASE = ['Galgo', 'Tanner', 'Nuevo Capital']
CARTERAS = [b + SUFIJO for b in CARTERAS_BASE]
ARBOL_TIPO = {
    'Galgo' + SUFIJO: Cartera.ARBOL_GALGO,
    'Tanner' + SUFIJO: Cartera.ARBOL_TANNER,
    'Nuevo Capital' + SUFIJO: Cartera.ARBOL_NUEVO_CAPITAL,
}
PREFIJO_OP = {'Galgo' + SUFIJO: 'GAL', 'Tanner' + SUFIJO: 'TAN', 'Nuevo Capital' + SUFIJO: 'NC'}
LEADS_POR_CARTERA = 40

NOMBRES = [
    'Ana Torres', 'Pedro Muñoz', 'Camila Rojas', 'Luis Fuentes', 'María Soto', 'Jorge Silva',
    'Paula Vega', 'Diego Castro', 'Valentina Reyes', 'Cristian Morales', 'Francisca Araya',
    'Rodrigo Pizarro', 'Javiera Contreras', 'Sebastián Herrera', 'Carolina Flores',
    'Matías Espinoza', 'Fernanda Bravo', 'Gonzalo Sepúlveda', 'Antonia Carrasco', 'Felipe Núñez',
]

COLECTORES = [
    ('demo_admin', 'admin'),
    ('demo_supervisor', 'supervisor'),
    ('demo_cobrador1', 'collector'),
    ('demo_cobrador2', 'collector'),
]


def _dv(rut):
    """Digito verificador chileno (modulo 11), solo para que los datos de demo se vean reales."""
    suma, factor = 0, 2
    for c in reversed(str(rut)):
        suma += int(c) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - (suma % 11)
    return {11: '0', 10: 'K'}.get(resto, str(resto))


class Command(BaseCommand):
    help = 'Genera datos de demo multi-cartera (Galgo/Tanner/Nuevo Capital) para el ambiente local.'

    def add_arguments(self, parser):
        parser.add_argument('--borrar', action='store_true', help='Elimina los datos de demo.')

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('generar_datos_demo solo puede correr con DEBUG=True (nunca en producción).')

        if options['borrar']:
            return self._borrar()

        with transaction.atomic():
            team, user_por_username = self._crear_equipo_y_usuarios()
            for nombre in CARTERAS:
                self._crear_cartera(nombre, team, user_por_username)

        self.stdout.write(self.style.SUCCESS(
            f'Listo. {len(CARTERAS)} cartera(s), {len(COLECTORES)} usuario(s) de demo '
            f'(password: demo1234), {LEADS_POR_CARTERA} lead(s) por cartera.'
        ))

    def _crear_equipo_y_usuarios(self):
        admin_user = None
        user_por_username = {}
        for username, user_type in COLECTORES:
            user, created = User.objects.get_or_create(
                username=username, defaults={'email': f'{username}@demo.turbotubo.local'},
            )
            if created:
                user.set_password('demo1234')
                user.save()
            # Userprofile ya existe (signal post_save de User) -- solo se ajusta el tipo.
            user.userprofile.user_type = user_type
            user.userprofile.must_change_password = False
            user.userprofile.save(update_fields=['user_type', 'must_change_password'])
            user_por_username[username] = user
            if user_type == 'admin':
                admin_user = user

        team, _ = Team.objects.get_or_create(name='Equipo Demo', defaults={'created_by': admin_user})
        for user in user_por_username.values():
            team.members.add(user)
            if not user.userprofile.active_team_id:
                user.userprofile.active_team = team
                user.userprofile.save(update_fields=['active_team'])

        return team, user_por_username

    def _crear_cartera(self, nombre, team, user_por_username):
        admin_user = user_por_username['demo_admin']
        cobrador = user_por_username['demo_cobrador1' if nombre != 'Nuevo Capital' else 'demo_cobrador2']

        cartera, created = Cartera.objects.get_or_create(nombre=nombre, defaults={'created_by': admin_user})
        subcartera = cartera.subcartera_default

        if not cartera.arbol_tipo:
            APLICAR_POR_TIPO[ARBOL_TIPO[nombre]](cartera)
            cartera.arbol_tipo = ARBOL_TIPO[nombre]
            cartera.arbol_asignado_at = timezone.now()
            cartera.arbol_asignado_por = admin_user
            cartera.save(update_fields=['arbol_tipo', 'arbol_asignado_at', 'arbol_asignado_por'])

        medio = Medio.objects.filter(cartera=cartera, canal=Medio.CANAL_TELEFONO, es_llamada=True).first()
        con_contacto = list(Resultado.objects.filter(cartera=cartera, contactabilidad=Resultado.CON_CONTACTO))
        sin_contacto = list(Resultado.objects.filter(cartera=cartera, contactabilidad=Resultado.SIN_CONTACTO))
        compromiso = [r for r in con_contacto if r.crea_compromiso]
        pagando = list(Resultado.objects.filter(cartera=cartera, efecto_pago=Resultado.EFECTO_PAGANDO))

        prefijo = PREFIJO_OP[nombre]
        creados = 0
        rng = random.Random(nombre)  # semilla fija por cartera: mismo dataset en cada corrida
        for i in range(1, LEADS_POR_CARTERA + 1):
            op = f'{prefijo}-{i:04d}'
            if Lead.objects.filter(op=op, subcartera=subcartera).exists():
                continue

            rut = 15000000 + rng.randint(0, 4000000)
            saldo = rng.randint(300_000, 4_000_000)
            lead = Lead.objects.create(
                team=team, op=op, subcartera=subcartera,
                name=rng.choice(NOMBRES), rut=rut, dv=_dv(rut),
                saldo_insoluto=saldo, saldo_deuda=saldo,
                valor_cuota=saldo // rng.randint(3, 12), cuotas_atrasadas=rng.randint(1, 6),
                created_by=admin_user, assigned_to=cobrador,
            )
            creados += 1

            phone = Phone.objects.create(
                lead=lead, phone_number=f'+5691{rng.randint(1000000, 9999999)}',
                phone_type=Phone.PRINCIPAL, phone_number_status='active',
            )
            id_demo = IDDemographics.objects.create(
                lead=lead, principal_email=f'lead{i}.{prefijo.lower()}@demo.cl',
                principal_email_status='active',
            )
            id_demo.principal_phones.add(phone)

            # Distribucion de escenarios: 40% sin contacto, 25% contactado, 20% compromiso,
            # 10% pagando, 5% sin gestion todavia (queda "recien asignado").
            roll = rng.random()
            if roll < 0.05 or not medio:
                continue
            if roll < 0.45 and sin_contacto:
                Action.objects.create(lead=lead, medio=medio, resultado=rng.choice(sin_contacto), user=cobrador, phone=phone)
            elif roll < 0.70 and con_contacto:
                candidatos = [r for r in con_contacto if not r.crea_compromiso and r.efecto_pago != Resultado.EFECTO_PAGANDO]
                Action.objects.create(lead=lead, medio=medio, resultado=rng.choice(candidatos or con_contacto), user=cobrador, phone=phone)
            elif roll < 0.90 and compromiso:
                fecha = timezone.now().date() + datetime.timedelta(days=rng.randint(-5, 20))
                Action.objects.create(
                    lead=lead, medio=medio, resultado=rng.choice(compromiso), user=cobrador, phone=phone,
                    fecha_compromiso=fecha, monto_compromiso=lead.valor_cuota,
                )
            elif pagando:
                Action.objects.create(lead=lead, medio=medio, resultado=rng.choice(pagando), user=cobrador, phone=phone)
                Payment.objects.create(
                    lead=lead, monto=lead.valor_cuota, fecha=timezone.now().date(), created_by=cobrador,
                )

        self.stdout.write(self.style.SUCCESS(f'{nombre}: árbol aplicado, {creados} lead(s) nuevo(s).'))

    def _borrar(self):
        carteras = Cartera.objects.filter(nombre__in=CARTERAS)
        n = carteras.count()

        # MapeoResultadoCampana (api app, Fase 4) protege su Medio/Resultado con PROTECT -- si se
        # sembró sobre una cartera demo (ej. via sembrar_mapeo_galgo --cartera "Galgo DEMO"),
        # Cartera.delete() fallaría en cascada sin esto. Import perezoso: lead no depende de api.
        try:
            from api.models import MapeoResultadoCampana
            MapeoResultadoCampana.objects.filter(cartera__in=carteras).delete()
        except LookupError:
            pass  # app 'api' no instalada en este ambiente

        Lead.objects.filter(subcartera__cartera__in=carteras).delete()
        carteras.delete()
        User.objects.filter(username__in=[u for u, _ in COLECTORES]).delete()
        Team.objects.filter(name='Equipo Demo').delete()
        self.stdout.write(self.style.SUCCESS(f'{n} cartera(s) de demo eliminada(s), usuarios y equipo también.'))
