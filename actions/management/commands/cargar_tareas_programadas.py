"""
Crea/actualiza en Celery Beat las tareas programadas del sistema (django_celery_beat ->
/admin -> Periodic Tasks). Idempotente: se puede volver a correr sin duplicar nada.

Por que un comando y no cargarlas a mano en /admin: son 13 tareas, cada una con su horario;
hacerlo a mano en cada ambiente es lento y facil de equivocar (un nombre mal escrito deja la
tarea sin correr y solo se nota cuando algo deja de pasar). Ademas, verificar_tareas_programadas
(actions/tasks.py) alerta si alguna de estas NO esta programada -- asi que la lista de aca y la
de HEARTBEAT_MAX_DIAS deben mantenerse alineadas.

Uso:  python manage.py cargar_tareas_programadas
      python manage.py cargar_tareas_programadas --dry-run
"""
from django.core.management.base import BaseCommand
from django.db import transaction

# (nombre visible, ruta de la tarea, tipo, cron/intervalo, para que sirve)
# Horarios en America/Santiago (CELERY_TIMEZONE). Las purgas van de madrugada, cuando no hay
# nadie gestionando; se escalonan de a 15 min para no pegarle todas juntas a la base.
TAREAS = [
    # --- alta frecuencia ---
    ('Sincronizar grabaciones PBX', 'actions.tasks.sync_pbx_recordings',
     'interval', (5, 'minutes'),
     'Baja las grabaciones de pbxip.cl de las llamadas recientes (ventana de 24h).'),

    # --- diarias ---
    ('Purgar gestiones por ciclo de vida', 'actions.tasks.purgar_gestiones_ciclo_vida',
     'crontab', ('0', '4', '*', '*', '*'),
     'Aplica la retencion de datos a las gestiones de leads terminados/desasignados.'),
    ('Reconciliar estados de leads', 'actions.tasks.reconciliar_estados',
     'crontab', ('0', '5', '*', '*', '*'),
     'Recalcula el status de los leads que quedaron desincronizados.'),
    ('Detectar compromisos rotos', 'actions.tasks.check_compromisos_rotos',
     'crontab', ('0', '6', '*', '*', '*'),
     'Marca como roto el compromiso vencido sin pago -> lead vuelve a Contactado.'),
    ('Verificar tareas programadas', 'actions.tasks.verificar_tareas_programadas',
     'crontab', ('0', '8', '*', '*', '*'),
     'Alerta (log ERROR "TAREAS_ATRASADAS") si alguna tarea critica dejo de correr.'),

    # --- semanales (domingo de madrugada) ---
    ('Purgar grabaciones vencidas', 'actions.tasks.purge_expired_recordings',
     'crontab', ('0', '3', '*', '*', '0'),
     'Borra las grabaciones que pasaron su retencion legal (2 anios).'),
    ('Purgar log de cambios de status', 'actions.tasks.purge_status_change_log',
     'crontab', ('15', '3', '*', '*', '0'),
     'Purga el detalle de StatusChangeLog (el mejor status vive en el lead, no se pierde).'),
    ('Purgar log de accesos', 'actions.tasks.purgar_access_log',
     'crontab', ('30', '3', '*', '*', '0'),
     'Purga el registro de accesos segun la politica de retencion.'),
    ('Purgar asignaciones antiguas', 'actions.tasks.purgar_asignaciones',
     'crontab', ('45', '3', '*', '*', '0'),
     'Purga el historial viejo de asignaciones de leads.'),
    ('Purgar compromisos rotos', 'actions.tasks.purgar_compromisos_rotos',
     'crontab', ('15', '4', '*', '*', '0'),
     'Purga los compromisos marcados como rotos pasada su ventana de retencion.'),
    ('Purgar historial de cargas masivas', 'actions.tasks.purgar_cargas_masivas',
     'crontab', ('30', '4', '*', '*', '0'),
     'Purga la bitacora de cargas masivas (tras esto ya no se pueden deshacer).'),
    ('Exportar metadata ML', 'mlmetadata.tasks.exportar_metadata_ml',
     'crontab', ('0', '5', '*', '*', '0'),
     'Exporta la metadata anonimizada de eventos a JSONL.'),

    # --- mensual ---
    ('Reset mensual de status', 'actions.tasks.reset_status_mensual',
     'crontab', ('30', '0', '1', '*', '*'),
     'El dia 1 de cada mes devuelve los leads a "no contactado" (no toca el status historico).'),
]


class Command(BaseCommand):
    help = 'Crea/actualiza las tareas programadas de Celery Beat (idempotente).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Muestra lo que haria, sin escribir en la base.')

    def handle(self, *args, **options):
        try:
            from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask
        except ImportError:
            self.stderr.write(self.style.ERROR('django_celery_beat no esta instalado.'))
            return

        from django.conf import settings
        tz = getattr(settings, 'CELERY_TIMEZONE', 'UTC')
        dry = options['dry_run']

        creadas = actualizadas = 0
        for nombre, ruta, tipo, spec, descripcion in TAREAS:
            if tipo == 'interval':
                cada, periodo = spec
                cuando = f'cada {cada} {periodo}'
                if dry:
                    horario = None
                else:
                    horario, _ = IntervalSchedule.objects.get_or_create(
                        every=cada, period=getattr(IntervalSchedule, periodo.upper()),
                    )
                campos = {'interval': horario, 'crontab': None}
            else:
                minuto, hora, dia_mes, mes, dia_semana = spec
                cuando = f'cron {minuto} {hora} {dia_mes} {mes} {dia_semana} ({tz})'
                if dry:
                    horario = None
                else:
                    horario, _ = CrontabSchedule.objects.get_or_create(
                        minute=minuto, hour=hora, day_of_month=dia_mes,
                        month_of_year=mes, day_of_week=dia_semana, timezone=tz,
                    )
                campos = {'crontab': horario, 'interval': None}

            if dry:
                self.stdout.write(f'  [dry-run] {nombre:<38} {ruta:<45} {cuando}')
                continue

            with transaction.atomic():
                tarea, creada = PeriodicTask.objects.update_or_create(
                    task=ruta,
                    defaults={'name': nombre, 'enabled': True,
                              'description': descripcion, **campos},
                )
            if creada:
                creadas += 1
                self.stdout.write(self.style.SUCCESS(f'  CREADA      {nombre:<38} {cuando}'))
            else:
                actualizadas += 1
                self.stdout.write(f'  actualizada {nombre:<38} {cuando}')

        if dry:
            self.stdout.write(self.style.WARNING(f'\n[dry-run] {len(TAREAS)} tarea(s), nada escrito.'))
            return

        self.stdout.write(self.style.SUCCESS(
            f'\nListo: {creadas} creada(s), {actualizadas} actualizada(s). Total: {len(TAREAS)}.'
        ))
        self.stdout.write('Se ven y editan en /admin -> Periodic Tasks.')
