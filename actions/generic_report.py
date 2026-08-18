"""
Reporte de gestiones "generico" (Excel, 16 columnas): para cualquier cartera que no tenga su
propio formato regulatorio. Nacio como el formato de Nuevo Capital (NuevoCapitalReportView, ver
actions/views.py) -- se extrae aca para que tanto la descarga manual como el envio automatico
(actions/reportes_automaticos.py) usen la MISMA implementacion, sin duplicar el armado de columnas.
"""
import datetime
from io import BytesIO

import openpyxl

# Mismas 16 columnas que el formato original de Nuevo Capital (Reporte Salida NC).
HEADERS = [
    'Operación', 'RUT', 'Dv', 'FechaGest', 'Hora Gest', 'Usuario', 'Accion',
    'Sub Estado', 'Estado', 'Comentario', 'Fecha Compromiso', 'Monto Compromiso',
    'Telefono', 'eMail', 'Origen Gestión', 'Externo',
]

# Todo TurboTubo hoy es una sola instancia de Zona Sur -- confirmado que este valor queda fijo,
# no configurable por config de reporte, sin importar la cartera.
EXTERNO = 'ZONA SUR'

REPORT_TZ = datetime.timezone(datetime.timedelta(hours=-4))


def construir_excel_generico(cartera, fecha_desde, fecha_hasta, subcartera_ids=None):
    """
    (filename, contenido_bytes) del Excel generico para esa cartera/rango, o None si no hubo
    gestiones. subcartera_ids=None o vacio = toda la cartera.
    """
    from .models import Action
    from .tanner_report import formatear_telefono
    from .views import _ejecutivo_nombre

    start = datetime.datetime.combine(fecha_desde, datetime.time.min, tzinfo=REPORT_TZ)
    end = datetime.datetime.combine(fecha_hasta, datetime.time.max, tzinfo=REPORT_TZ)

    actions = Action.objects.filter(
        subcartera__cartera=cartera,
        created_at__gte=start,
        created_at__lte=end,
    ).select_related('lead', 'medio', 'resultado', 'user', 'phone')

    if subcartera_ids:
        actions = actions.filter(subcartera_id__in=subcartera_ids)

    if not actions.exists():
        return None

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = 'Reporte de gestiones'
    sheet.append(HEADERS)

    for action in actions:
        lead = action.lead
        local_dt = action.created_at.astimezone(REPORT_TZ)
        origen = '1' if action.es_entrante else '2'  # In=1 / Out=2
        sub_estado = action.resultado.tipo_contacto or ''
        compromiso = action.fecha_compromiso.strftime('%d-%m-%Y') if action.fecha_compromiso else ''

        sheet.append([
            lead.op,
            lead.rut,
            lead.dv,
            local_dt.strftime('%d-%m-%Y'),
            local_dt.strftime('%H:%M:%S'),
            _ejecutivo_nombre(action.user),
            action.medio.nombre,
            sub_estado,
            action.resultado.nombre,
            action.comment or '',
            compromiso,
            action.monto_compromiso if action.monto_compromiso else '',
            formatear_telefono(action.phone.phone_number) if action.phone else '',
            action.email or '',
            origen,
            EXTERNO,
        ])

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    if fecha_desde == fecha_hasta:
        filename = f"Reporte_Gestiones_{cartera.slug}_{fecha_desde:%Y%m%d}.xlsx"
    else:
        filename = f"Reporte_Gestiones_{cartera.slug}_{fecha_desde:%Y%m%d}_a_{fecha_hasta:%Y%m%d}.xlsx"
    return filename, output.getvalue()
