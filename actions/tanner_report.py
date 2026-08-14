"""
Generacion del archivo de gestiones para Tanner (formato oficial del instructivo).

Vive aparte de actions/views.py porque lo usan DOS caminos: la descarga de un dia (sincrona, en
el request) y el reporte por RANGO de fechas, que corre en el WORKER de Celery
(actions.tasks.generar_reporte_tanner_rango). Tener una sola implementacion evita que los dos
formatos se desincronicen -- es un archivo regulatorio, no puede haber dos versiones.

Formato: 15 columnas separadas por '|', SIN encabezado, un dia por archivo,
nombre FechaGestiones_BaseGestiones2_40.txt. Cada linea lleva su propia fecha y hora, por eso
concatenar varios dias en un solo archivo no rompe nada.

Las columnas 1-14 son las que lista el instructivo; la 15 ("Reporte Texto" de la paleta oficial)
no esta en esa lista pero SI viene en el archivo de ejemplo de Tanner y en todo lo que se le ha
enviado y aceptado -- ver reporte_texto() mas abajo.
"""
import datetime
import re

TANNER_GESTOR_CODIGO = '40'  # ZONASUR, tabla de gestores del instructivo Tanner
TANNER_TIPO_GESTION_DEFAULT = '1'  # Cobranza
TANNER_ORIGEN_GESTION_DEFAULT = '2'  # Outbound

# Columna 15 ("Reporte Texto" en la paleta oficial de Tanner). No aparece en la lista de columnas
# del instructivo, pero SI viene en el archivo de ejemplo que entrega Tanner y en todo lo que se
# le ha enviado y aceptado -- por eso se emite.
#
# La regla sale de la paleta oficial (Paleta Respuesta Tanner-.xlsx), cruzando Accion x Estado:
# son 165 combinaciones y ninguna es ambigua. Se reduce a esto:
#   - medios de mensajeria (SMS, Email, WhatsApp, IVR): '2' si el mensaje se entrego, '1' si no.
#   - medios de voz/presencial (manual, discador, terreno): vacio.
# El valor '4' que aparece en los archivos reales corresponde a gestiones ENTRANTES (el cliente
# respondio), que hoy no se pueden distinguir porque el arbol no separa las acciones "RECIBIDO".
TANNER_REPORTE_ENTREGADO = '2'
TANNER_REPORTE_NO_ENTREGADO = '1'
TANNER_REPORTE_SIN_TEXTO = ''

# Medios cuyo resultado describe la entrega de un mensaje (codigos del instructivo Tanner).
MEDIOS_MENSAJERIA = {'4', '5', '6', '7', '8'}  # IVR, SMS, Email, WhatsApp, Bot


def reporte_texto(medio_codigo, resultado_nombre):
    """Columna 15 del reporte, segun la paleta oficial de Tanner."""
    if str(medio_codigo) not in MEDIOS_MENSAJERIA:
        return TANNER_REPORTE_SIN_TEXTO
    nombre = (resultado_nombre or '').upper()
    if 'NO ENTREGADO' in nombre or 'INCOMPLETO' in nombre:
        return TANNER_REPORTE_NO_ENTREGADO
    return TANNER_REPORTE_ENTREGADO

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
    """NOMBRE APELLIDO en mayusculas, como lo espera Tanner.

    Si el usuario no tiene nombre/apellido cargados se cae al username, que suele venir sin
    separador ("ivanpottstock" -> "IVANPOTTSTOCK"). Eso no se puede partir sin adivinar donde
    termina el nombre, asi que se emite tal cual: la solucion real es cargarle nombre y apellido
    al usuario en Configuracion -> Usuarios.
    """
    if not user:
        return ''
    nombre = (user.first_name or '').strip()
    apellido = (user.last_name or '').strip()
    if nombre or apellido:
        return ' '.join(parte for parte in (nombre, apellido) if parte).upper()
    return (user.username or '').strip().upper()


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
    """Las 15 columnas del reporte, una linea por gestion."""
    lineas = []
    for action in actions:
        lead = action.lead
        rut_cliente = f"{lead.rut}{lead.dv}"
        compromiso = action.fecha_compromiso.strftime('%d-%m-%Y') if action.fecha_compromiso else ''
        # Tanner recibe la observacion con un espacio final (asi la emitia el sistema anterior y
        # asi quedo en los archivos ya aceptados). Se agrega SOLO al exportar; la gestion guardada
        # no se toca.
        observacion = (action.comment or '').replace('|', ' ').replace('\n', ' ')[:255] + ' '
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
            # Segundos siempre en :00 -- es el formato que Tanner viene recibiendo (el sistema
            # anterior nunca envio segundos reales). Solo afecta al EXPORTE: la gestion se sigue
            # guardando con su hora exacta, que es la que se ve en la ficha y en los reportes
            # internos.
            local_dt.strftime('%H:%M:00'),
            nombre_ejecutivo(action.user),
            formatear_telefono(action.phone.phone_number) if action.phone else '',
            action.email or '',
            TANNER_TIPO_GESTION_DEFAULT,
            TANNER_ORIGEN_GESTION_DEFAULT,
            reporte_texto(action.medio.codigo, action.resultado.nombre),
        ]
        lineas.append('|'.join(str(value) for value in row))
    return lineas


def contenido_del_dia(fecha, user, subcartera_id=None):
    """(contenido_txt, cantidad_de_gestiones) de un dia. Contenido vacio si no hubo gestiones."""
    lineas = construir_lineas(gestiones_del_dia(fecha, user, subcartera_id))
    if not lineas:
        return '', 0
    return '\r\n'.join(lineas) + '\r\n', len(lineas)
