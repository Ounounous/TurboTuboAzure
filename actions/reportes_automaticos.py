"""
Logica de negocio de los reportes automaticos por email (ver actions/models.py:
ReporteAutomaticoConfig). Separado de actions/tasks.py (orquestacion Celery) igual que
tanner_report.py esta separado de tasks.py -- funciones puras, faciles de probar sin worker.
"""
import datetime
import logging

from django.utils import timezone

from .models import Cartera, ReporteAutomaticoConfig

logger = logging.getLogger(__name__)


def corresponde_enviar_hoy(config, hoy=None):
    """
    True si, segun la periodicidad de la config, hoy toca enviar.

    Approach: dias transcurridos desde la fecha de creacion de la config, modulo N. Determinista,
    no requiere guardar una "proxima fecha de envio" en un campo aparte. Trade-off aceptado: si se
    edita cada_x_dias, la cadencia se recalcula desde la MISMA fecha de creacion (no desde la
    fecha de edicion) -- evita un campo extra "fecha_ancla" editable que complicaria la UI sin
    necesidad real hoy.
    """
    hoy = hoy or timezone.localdate()

    if config.saltar_fines_de_semana and hoy.weekday() >= 5:  # 5=sabado, 6=domingo
        return False

    if config.periodicidad == ReporteAutomaticoConfig.PERIODICIDAD_DIARIA:
        dias = 1
    elif config.periodicidad == ReporteAutomaticoConfig.PERIODICIDAD_SEMANAL:
        dias = 7
    else:
        dias = max(1, config.cada_x_dias)

    ancla = config.created_at.date()
    return (hoy - ancla).days % dias == 0


def rango_pendiente(config, hoy=None):
    """
    (fecha_desde, fecha_hasta) que le corresponde cubrir al proximo envio. fecha_hasta siempre es
    "ayer" (el dia cerrado mas reciente, mismo criterio que ya usan los reportes manuales de
    Tanner/Nuevo Capital). fecha_desde depende de ultimo_envio_ok_at:
      - Sin envios exitosos previos: solo el dia anterior (no hay de donde acumular).
      - Con un envio exitoso previo: desde el dia siguiente a ese envio -- asi un reporte semanal
        trae TODA la semana, no solo el ultimo dia.
    Si por algun motivo fecha_desde termina despues de fecha_hasta (ej. "enviar de prueba" se uso
    dos veces el mismo dia), se acota a un solo dia -- nunca un rango invertido.
    """
    hoy = hoy or timezone.localdate()
    fecha_hasta = hoy - datetime.timedelta(days=1)

    if config.ultimo_envio_ok_at is None:
        fecha_desde = fecha_hasta
    else:
        fecha_desde = config.ultimo_envio_ok_at.date() + datetime.timedelta(days=1)
        if fecha_desde > fecha_hasta:
            fecha_desde = fecha_hasta

    return fecha_desde, fecha_hasta


def generar_adjunto_reporte(config, fecha_desde, fecha_hasta):
    """
    (filename, contenido_bytes, content_type) del reporte que corresponde a esta config para el
    rango dado, o None si no hubo gestiones en ningun dia del rango.
    """
    subcartera_ids = list(config.subcarteras.values_list('pk', flat=True))

    if config.tipo_reporte == ReporteAutomaticoConfig.TIPO_ESTANDAR and config.cartera.arbol_tipo == Cartera.ARBOL_TANNER:
        return _adjunto_tanner(config, fecha_desde, fecha_hasta, subcartera_ids)
    return _adjunto_generico(config, fecha_desde, fecha_hasta, subcartera_ids)


def _adjunto_tanner(config, fecha_desde, fecha_hasta, subcartera_ids):
    """
    ZIP con un .txt POR DIA (formato regulatorio: un archivo por dia, nombre oficial) mas un
    consolidado -- mismo patron que actions/tasks.py::generar_reporte_tanner_rango, pero devuelto
    en memoria para adjuntar al email en vez de guardarse en un ReporteTannerJob.
    """
    import io
    import zipfile

    from .tanner_report import construir_lineas, nombre_archivo, resultados_sin_codigo
    from .tanner_report import gestiones_del_dia_multi

    buf = io.BytesIO()
    total = 0
    dias_con_datos = 0
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        consolidado = []
        fecha = fecha_desde
        while fecha <= fecha_hasta:
            acciones = list(gestiones_del_dia_multi(fecha, config.cartera, subcartera_ids))
            lineas = construir_lineas(acciones)
            if lineas:
                contenido = '\r\n'.join(lineas) + '\r\n'
                zf.writestr(nombre_archivo(fecha), contenido)
                consolidado.extend(lineas)
                total += len(lineas)
                dias_con_datos += 1
                sin_codigo = resultados_sin_codigo(acciones)
                if sin_codigo:
                    nombres = sorted({a.resultado.nombre for a in sin_codigo})
                    logger.warning(
                        f"_adjunto_tanner: config {config.pk}, {fecha}: "
                        f"{len(sin_codigo)} gestion(es) con resultado sin codigo: {', '.join(nombres)}"
                    )
            fecha += datetime.timedelta(days=1)

        if not consolidado:
            return None

        # Rango de un solo dia: el archivo del dia (ya escrito arriba, mismo nombre oficial) ES el
        # consolidado -- agregar otro con ese mismo nombre duplicaria la entrada en el ZIP.
        if fecha_desde != fecha_hasta:
            nombre_consolidado = f"{fecha_desde:%Y%m%d}_a_{fecha_hasta:%Y%m%d}_BaseGestiones2_40_consolidado.txt"
            zf.writestr(nombre_consolidado, '\r\n'.join(consolidado) + '\r\n')

    buf.seek(0)
    if fecha_desde == fecha_hasta:
        zip_name = f"Reporte_Tanner_{fecha_desde:%Y%m%d}.zip"
    else:
        zip_name = f"Reporte_Tanner_{fecha_desde:%Y%m%d}_a_{fecha_hasta:%Y%m%d}.zip"
    return zip_name, buf.getvalue(), 'application/zip'


def _adjunto_generico(config, fecha_desde, fecha_hasta, subcartera_ids):
    from .generic_report import construir_excel_generico

    resultado = construir_excel_generico(config.cartera, fecha_desde, fecha_hasta, subcartera_ids or None)
    if resultado is None:
        return None
    filename, contenido = resultado
    return filename, contenido, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
