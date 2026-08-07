"""
Generacion del archivo de gestiones para Tanner (formato oficial del instructivo).

Vive aparte de actions/views.py porque lo usan DOS caminos: la descarga de un dia (sincrona, en
el request) y el reporte por RANGO de fechas, que corre en el WORKER de Celery
(actions.tasks.generar_reporte_tanner_rango). Tener una sola implementacion evita que los dos
formatos se desincronicen -- es un archivo regulatorio, no puede haber dos versiones.

Formato: 14 columnas separadas por '|', SIN encabezado, un dia por archivo,
nombre FechaGestiones_BaseGestiones2_40.txt. Cada linea lleva su propia fecha y hora, por eso
concatenar varios dias en un solo archivo no rompe nada.
"""
import datetime
import re

TANNER_GESTOR_CODIGO = '40'  # ZONASUR, tabla de gestores del instructivo Tanner
TANNER_TIPO_GESTION_DEFAULT = '1'  # Cobranza
TANNER_ORIGEN_GESTION_DEFAULT = '2'  # Outbound

# Zona del reporte (UTC-4): define a que dia pertenece cada gestion.
REPORT_TZ = datetime.timezone(datetime.timedelta(hours=-4))


def formatear_telefono(raw_number):
    digits = re.sub(r'\D', '', raw_number or '')
    if not digits:
        return ''
    if digits.startswith('56'):
        return digits
    if len(digits) == 9:
        return '56' + digits
    return digits


def nombre_ejecutivo(user):
    if not user:
        return ''
    full = user.get_full_name().strip()
    return (full or user.username).upper()


def nombre_archivo(fecha, subcartera=None):
    """Nombre EXACTO que exige el instructivo. El sufijo de subcartera solo se agrega cuando se
    filtra: el archivo combinado (el oficial que se envia a Tanner) no lleva nada extra."""
    sufijo = ''
    if subcartera is not None:
        sufijo = f"_{re.sub(r'[^A-Za-z0-9]+', '', subcartera.nombre)}"
    return f"{fecha.strftime('%Y%m%d')}_BaseGestiones2_{TANNER_GESTOR_CODIGO}{sufijo}.txt"


def gestiones_del_dia(fecha, user, subcartera_id=None):
    """Queryset de gestiones de Tanner de ese dia. Con `subcartera_id` se acota ADEMAS al alcance
    real de `user` (pedir "mi subcartera" no puede devolver la de otro supervisor); sin el, es el
    reporte oficial de toda la cartera, que cualquier supervisor puede generar."""
    from lead.permissions import scope_por_lead

    from .models import Action

    start = datetime.datetime.combine(fecha, datetime.time.min, tzinfo=REPORT_TZ)
    end = datetime.datetime.combine(fecha, datetime.time.max, tzinfo=REPORT_TZ)

    actions = Action.objects.filter(
        subcartera__cartera__nombre__iexact='Tanner',
        created_at__gte=start,
        created_at__lte=end,
    ).select_related('lead', 'medio', 'resultado', 'user__userprofile', 'phone')

    if subcartera_id:
        actions = scope_por_lead(actions, user).filter(subcartera_id=subcartera_id)
    return actions.order_by('created_at')


def construir_lineas(actions):
    """Las 14 columnas del instructivo, una linea por gestion."""
    lineas = []
    for action in actions:
        lead = action.lead
        rut_cliente = f"{lead.rut}{lead.dv}"
        compromiso = action.fecha_compromiso.strftime('%d-%m-%Y') if action.fecha_compromiso else ''
        observacion = (action.comment or '').replace('|', ' ').replace('\n', ' ')[:255]
        local_dt = action.created_at.astimezone(REPORT_TZ)

        row = [
            lead.op,
            rut_cliente,
            TANNER_GESTOR_CODIGO,
            compromiso,
            action.resultado.codigo,
            observacion,
            action.medio.codigo,
            local_dt.strftime('%d-%m-%Y'),
            local_dt.strftime('%H:%M:%S'),
            nombre_ejecutivo(action.user),
            formatear_telefono(action.phone.phone_number) if action.phone else '',
            action.email or '',
            TANNER_TIPO_GESTION_DEFAULT,
            TANNER_ORIGEN_GESTION_DEFAULT,
        ]
        lineas.append('|'.join(str(value) for value in row))
    return lineas


def contenido_del_dia(fecha, user, subcartera_id=None):
    """(contenido_txt, cantidad_de_gestiones) de un dia. Contenido vacio si no hubo gestiones."""
    lineas = construir_lineas(gestiones_del_dia(fecha, user, subcartera_id))
    if not lineas:
        return '', 0
    return '\r\n'.join(lineas) + '\r\n', len(lineas)
