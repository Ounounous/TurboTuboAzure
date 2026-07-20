"""
Comando de SOLO LECTURA contra la base de datos vieja (turbotubobeta en Azure), el primer paso
del ensayo de migracion de datos reales (ver plan post-Azure). No escribe nada, nunca. Sirve
para confirmar que el esquema realmente desplegado coincide con lo que vemos en la rama `main`
(que quedo congelada justo antes del refactor multi-cartera) antes de construir el script que
transforma esos datos en los Excel que la app ya sabe validar y cargar.

Requiere que LEGACY_DB_HOST (y LEGACY_DB_NAME/USER/PASSWORD/PORT) esten definidos en el .env
local -- ver .env.example. Nunca imprime la contraseña ni datos personales (nombre/rut/telefono/
email/direccion): solo conteos de filas y la distribucion de los campos de choices, que es lo
que hace falta para armar el mapeo de la migracion real.

Uso:
    python manage.py inspeccionar_legacy
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.utils import OperationalError


TABLAS_ESPERADAS = [
    'team_team',
    'auth_user',
    'userprofile_userprofile',
    'lead_lead',
    'lead_statuschangelog',
    'lead_leadassignment',
    'lead_comment',
    'lead_leadfile',
    'demographics_iditem',
    'demographics_phone',
    'demographics_iddemographics',
    'demographics_avaldemographics',
    'actions_action',
]

# columna -> (tabla, [columnas de choice a distribuir])
DISTRIBUCIONES = {
    'lead_lead': ['cartera', 'status', 'activo', 'tipo_cobranza', 'ciclo_cartera', 'ciclo', 'tiene_aval'],
    'actions_action': ['action_type', 'result', 'target'],
    'userprofile_userprofile': ['user_type'],
}


class Command(BaseCommand):
    help = 'Inspecciona (solo lectura) la base de datos vieja de turbotubobeta antes de migrar.'

    def handle(self, *args, **options):
        if 'legacy' not in connections.databases:
            raise CommandError(
                'No hay conexion "legacy" configurada. Define LEGACY_DB_HOST (y _NAME/_USER/'
                '_PASSWORD/_PORT si no son los default) en tu .env local -- nunca lo pegues en '
                'el chat, solo agregalo al archivo. Ver .env.example.'
            )

        conn = connections['legacy']
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT current_database(), version()')
                dbname, version = cur.fetchone()
        except OperationalError as e:
            raise CommandError(f'No se pudo conectar a la base legacy: {e}')

        self.stdout.write(self.style.SUCCESS(f'Conectado a "{dbname}".'))
        self.stdout.write(version.split(',')[0])
        self.stdout.write('')

        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
            tablas_reales = {row[0] for row in cur.fetchall()}

        for tabla in TABLAS_ESPERADAS:
            if tabla not in tablas_reales:
                self.stdout.write(self.style.WARNING(f'{tabla}: NO EXISTE (el esquema real difiere de main)'))
                continue
            with conn.cursor() as cur:
                cur.execute(f'SELECT COUNT(*) FROM "{tabla}"')
                n = cur.fetchone()[0]
            self.stdout.write(f'{tabla}: {n} fila(s)')

        extra = tablas_reales - set(TABLAS_ESPERADAS)
        conocidas_django = {'django_migrations', 'django_content_type', 'django_admin_log',
                             'django_session', 'auth_group', 'auth_permission',
                             'auth_group_permissions', 'auth_user_groups', 'auth_user_user_permissions'}
        extra_relevante = sorted(t for t in extra if t not in conocidas_django)
        if extra_relevante:
            self.stdout.write('')
            self.stdout.write('Tablas adicionales no esperadas (revisar si son relevantes):')
            for t in extra_relevante:
                self.stdout.write(f'  - {t}')

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Distribucion de campos de choice (sin datos personales):'))
        for tabla, columnas in DISTRIBUCIONES.items():
            if tabla not in tablas_reales:
                continue
            for columna in columnas:
                with conn.cursor() as cur:
                    try:
                        cur.execute(
                            f'SELECT "{columna}", COUNT(*) FROM "{tabla}" GROUP BY "{columna}" ORDER BY COUNT(*) DESC'
                        )
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f'  {tabla}.{columna}: no se pudo leer ({e})'))
                        continue
                    filas = cur.fetchall()
                self.stdout.write(f'{tabla}.{columna}:')
                for valor, n in filas:
                    self.stdout.write(f'    {valor!r}: {n}')

        if 'lead_lead' in tablas_reales:
            with conn.cursor() as cur:
                cur.execute('SELECT MIN(created_at), MAX(created_at), COUNT(DISTINCT team_id) FROM lead_lead')
                min_dt, max_dt, n_teams = cur.fetchone()
            self.stdout.write('')
            self.stdout.write(f'lead_lead.created_at: {min_dt} .. {max_dt} -- {n_teams} team(s) distinto(s)')

        if 'actions_action' in tablas_reales:
            with conn.cursor() as cur:
                cur.execute('SELECT MIN(created_at), MAX(created_at) FROM actions_action')
                min_dt, max_dt = cur.fetchone()
            self.stdout.write(f'actions_action.created_at: {min_dt} .. {max_dt}')

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Listo. Nada fue modificado (conexion de solo lectura).'))
