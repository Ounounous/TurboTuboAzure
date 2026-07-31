"""
Rangos de fecha en hora local (America/Santiago) para filtrar campos DateTimeField.

Por que existe: filtrar con `created_at__date=hoy` obliga a Postgres a evaluar
`(created_at AT TIME ZONE 'America/Santiago')::date` fila por fila. Al ser una EXPRESION sobre
la columna, un indice comun sobre created_at NO se puede usar -- la consulta termina siempre en
recorrido completo de tabla, y eso crece lineal con la cantidad de gestiones.

`rango_local()` traduce el mismo criterio a un rango [inicio, fin) de datetimes con zona, que
SI usa el indice. La semantica es identica: "las gestiones del dia en hora chilena".
"""
import datetime

from django.utils import timezone


def rango_local(fecha_inicio, fecha_fin_exclusiva):
    """(inicio, fin) con zona, desde la medianoche local de fecha_inicio hasta la medianoche
    local de fecha_fin_exclusiva. Pensado para `campo__gte=inicio, campo__lt=fin`."""
    tz = timezone.get_current_timezone()
    inicio = timezone.make_aware(datetime.datetime.combine(fecha_inicio, datetime.time.min), tz)
    fin = timezone.make_aware(datetime.datetime.combine(fecha_fin_exclusiva, datetime.time.min), tz)
    return inicio, fin


def rango_del_dia(fecha):
    """(inicio, fin) que cubre un unico dia local completo."""
    return rango_local(fecha, fecha + datetime.timedelta(days=1))
