"""
Bitacora de cargas masivas: deja un rastro de que creo o modifico cada Excel subido, para poder
deshacer un lote completo si se cargo con datos malos (ej. a los leads equivocados).

Uso desde una vista de carga (ver actions/views.py, demographics/views.py, lead/views.py,
suspensiones/views.py para ejemplos reales):

    lote = iniciar_lote('telefonos', request.user, archivo_nombre=excel_file.name, total_filas=len(resultado.filas))
    for fila in resultado.filas:
        obj, created = Modelo.objects.get_or_create(...)
        if created:
            obj.campo = valor
            obj.save()
            registrar_creacion(lote, obj)
        else:
            registrar_actualizacion(lote, obj, {'campo': valor})  # ANTES de tocar obj.campo
            obj.campo = valor
            obj.save()

Deshacer: deshacer_lote(lote, usuario_que_deshace).
"""
import datetime
import decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import DateField, DateTimeField, DecimalField
from django.utils import timezone

from .models import CargaMasiva, CargaMasivaCambio


def iniciar_lote(tipo, usuario, archivo_nombre='', total_filas=0):
    return CargaMasiva.objects.create(
        tipo=tipo, usuario=usuario, archivo_nombre=archivo_nombre, total_filas=total_filas,
    )


def _serializar(valor):
    """A JSON no le gustan Decimal/date/datetime -- se guardan como texto y se reconstruyen al
    deshacer segun el tipo real del campo del modelo (ver _deserializar)."""
    if isinstance(valor, decimal.Decimal):
        return str(valor)
    if isinstance(valor, (datetime.date, datetime.datetime)):
        return valor.isoformat()
    if hasattr(valor, 'pk'):  # instancia de modelo (ej. un FK asignado directo, no _id)
        return valor.pk
    return valor


def _deserializar(modelo, campo, valor):
    if valor is None:
        return None
    try:
        field = modelo._meta.get_field(campo)
    except Exception:
        return valor
    if isinstance(field, DateTimeField):
        from django.utils.dateparse import parse_datetime
        return parse_datetime(valor)
    if isinstance(field, DateField):
        from django.utils.dateparse import parse_date
        return parse_date(valor)
    if isinstance(field, DecimalField):
        return decimal.Decimal(valor)
    return valor


def registrar_creacion(lote, obj):
    """Llamar DESPUES de obj.save() (necesita el pk ya asignado)."""
    CargaMasivaCambio.objects.create(
        lote=lote,
        content_type=ContentType.objects.get_for_model(obj),
        object_id=obj.pk,
        accion=CargaMasivaCambio.ACCION_CREADO,
        valores_anteriores=None,
    )


def registrar_actualizacion(lote, obj, campos_nuevos):
    """Llamar ANTES de aplicar campos_nuevos (dict campo->valor_nuevo) sobre obj -- lee el valor
    ACTUAL de cada campo (el que se va a perder) para poder restaurarlo despues."""
    valores = {campo: (getattr(obj, campo), nuevo) for campo, nuevo in campos_nuevos.items()}
    registrar_actualizacion_valores(lote, obj, valores)


def registrar_actualizacion_valores(lote, obj, valores_antes_despues):
    """Como registrar_actualizacion, pero para cuando el 'antes' no se puede leer del objeto en
    el momento de llamar -- ej. la mutacion ya la hizo una funcion externa (lead.lifecycle.
    suspender/desasignar/reactivar). valores_antes_despues: {'campo': (valor_antes, valor_despues)}."""
    valores = {
        campo: [_serializar(antes), _serializar(despues)]
        for campo, (antes, despues) in valores_antes_despues.items()
    }
    CargaMasivaCambio.objects.create(
        lote=lote,
        content_type=ContentType.objects.get_for_model(obj),
        object_id=obj.pk,
        accion=CargaMasivaCambio.ACCION_ACTUALIZADO,
        valores_anteriores=valores,
    )


def deshacer_lote(lote, usuario):
    """Revierte un lote completo: filas creadas se borran (en cascada segun las FK normales del
    modelo -- Lead se lleva sus gestiones/pagos, pero NO las grabaciones, que son SET_NULL);
    filas actualizadas vuelven a su valor anterior. Recorre los cambios en orden inverso (mas
    reciente primero) por si hubiera dependencias entre filas del mismo lote."""
    if lote.estado == CargaMasiva.DESHECHA:
        raise ValueError('Este lote ya fue deshecho.')

    with transaction.atomic():
        for cambio in lote.cambios.select_related('content_type').order_by('-id'):
            modelo = cambio.content_type.model_class()
            if modelo is None:
                continue
            if cambio.accion == CargaMasivaCambio.ACCION_CREADO:
                modelo.objects.filter(pk=cambio.object_id).delete()
            else:
                obj = modelo.objects.filter(pk=cambio.object_id).first()
                if obj is None:
                    continue
                update_fields = []
                for campo, (anterior, _nuevo) in cambio.valores_anteriores.items():
                    setattr(obj, campo, _deserializar(modelo, campo, anterior))
                    update_fields.append(campo)
                obj.save(update_fields=update_fields)

        lote.estado = CargaMasiva.DESHECHA
        lote.deshecha_at = timezone.now()
        lote.deshecha_por = usuario
        lote.save(update_fields=['estado', 'deshecha_at', 'deshecha_por'])
