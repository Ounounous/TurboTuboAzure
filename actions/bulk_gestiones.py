"""
Validacion de la carga masiva de gestiones (Excel).

Vive aparte de actions/views.py porque ahora la usa el WORKER de Celery
(actions.tasks.procesar_carga_gestiones), no el proceso web: un Excel de decenas de miles de
filas tarda mas que el limite de espera del proxy de Azure. La vista solo recibe el archivo.
"""
import datetime
import re

from django.contrib.auth.models import User
from django.utils.dateparse import parse_date

from demographics.models import Phone
from demographics.views import find_lead

from .models import Medio, Resultado

BULK_COLUMN_ALIASES = {
    'cartera': 'cartera',
    'subcartera': 'subcartera',
    'op': 'op', 'operacion': 'op', 'id': 'op',
    'medio': 'medio', 'accion': 'medio',
    'resultado': 'resultado', 'estado': 'resultado',
    'sub_estado': 'sub_estado', 'subestado': 'sub_estado', 'tipo_contacto': 'sub_estado',
    'comentario': 'comentario', 'comment': 'comentario', 'observacion': 'comentario',
    'telefono': 'telefono', 'phone': 'telefono', 'fono': 'telefono',
    'email': 'email', 'correo': 'email', 'mail': 'email',
    'fecha_gestion': 'fecha_gestion', 'fecha': 'fecha_gestion',
    'hora_gestion': 'hora_gestion', 'hora': 'hora_gestion',
    'usuario': 'usuario', 'user': 'usuario', 'ejecutivo': 'usuario',
}

BULK_TEMPLATE_HEADERS = [
    'cartera', 'subcartera', 'op', 'medio', 'resultado', 'sub_estado',
    'comentario', 'telefono', 'email', 'fecha_gestion', 'hora_gestion', 'usuario',
]

BULK_TEMPLATE_EXAMPLE = [
    'Nuevo Capital', 'ZONA SUR', 'NC-001', 'IVR', 'CONTACTADO', 'DIRECTO',
    'Campaña IVR 14-07', '56977665544', '', '2026-07-14', '15:30', '',
]


def parse_fecha(value):
    """Acepta datetime/date de openpyxl o texto (YYYY-MM-DD o DD-MM-YYYY / DD/MM/YYYY)."""
    if value in (None, ''):
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    parsed = parse_date(text)
    if parsed:
        return parsed
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d'):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_hora(value):
    """Acepta time/datetime de openpyxl o texto (HH:MM o HH:MM:SS)."""
    if value in (None, ''):
        return None
    if isinstance(value, datetime.datetime):
        return value.time()
    if isinstance(value, datetime.time):
        return value
    text = str(value).strip()
    for fmt in ('%H:%M:%S', '%H:%M', '%H.%M'):
        try:
            return datetime.datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def construir_validador(usuario):
    """
    Devuelve la funcion validar_fila(fila, rownum) que espera core.bulk_upload.procesar_carga,
    con sus caches ya armados (medios/resultados por cartera, usuarios por nombre) para no
    repetir la misma consulta por cada una de las miles de filas.

    `usuario` es quien subio el archivo: se usa como autor por defecto de las gestiones cuya
    columna "usuario" viene vacia o no calza con ningun usuario del sistema.
    """
    medios_cache, resultados_cache, user_cache = {}, {}, {}

    def get_medios(cartera):
        if cartera.id not in medios_cache:
            medios_cache[cartera.id] = {
                m.nombre.strip().upper(): m for m in Medio.objects.filter(cartera=cartera)
            }
        return medios_cache[cartera.id]

    def get_resultados(cartera):
        if cartera.id not in resultados_cache:
            exact, by_name = {}, {}
            for r in Resultado.objects.filter(cartera=cartera):
                nom = r.nombre.strip().upper()
                exact[(nom, (r.tipo_contacto or '').strip().upper())] = r
                by_name.setdefault(nom, []).append(r)
            resultados_cache[cartera.id] = {'exact': exact, 'by_name': by_name}
        return resultados_cache[cartera.id]

    def get_user(username):
        key = (username or '').strip().lower()
        if not key:
            return None
        if key not in user_cache:
            user_cache[key] = User.objects.filter(username__iexact=key).first()
        return user_cache[key]

    def validar_fila(fila, rownum):
        errores = []
        cartera_nom, subcartera_nom, op = fila.get('cartera'), fila.get('subcartera'), fila.get('op')
        medio_nom, resultado_nom = fila.get('medio'), fila.get('resultado')
        if not (cartera_nom and subcartera_nom and op and medio_nom and resultado_nom):
            return None, ['faltan datos obligatorios (cartera, subcartera, op, medio o resultado)']

        lead = find_lead(cartera_nom, subcartera_nom, op)
        if not lead:
            return None, [f'no se encontró el lead OP={op} en {cartera_nom} / {subcartera_nom}']

        cartera = lead.subcartera.cartera
        medio = get_medios(cartera).get(str(medio_nom).strip().upper())
        if not medio:
            errores.append(f'la cartera {cartera.nombre} no tiene el medio "{medio_nom}"')

        res_data = get_resultados(cartera)
        nom_up = str(resultado_nom).strip().upper()
        sub_estado = fila.get('sub_estado')
        resultado = None
        if sub_estado:
            resultado = res_data['exact'].get((nom_up, str(sub_estado).strip().upper()))
            if not resultado:
                errores.append(
                    f'no existe el resultado "{resultado_nom}" con sub estado "{sub_estado}" en {cartera.nombre}'
                )
        else:
            candidatos = res_data['by_name'].get(nom_up, [])
            if not candidatos:
                errores.append(f'la cartera {cartera.nombre} no tiene el resultado "{resultado_nom}"')
            elif len(candidatos) > 1:
                errores.append(
                    f'el resultado "{resultado_nom}" es ambiguo en {cartera.nombre}; agrega la columna sub_estado'
                )
            else:
                resultado = candidatos[0]

        # La carga masiva no tiene columna de fecha de compromiso (cargar promesas de pago en
        # bloque no tiene sentido de negocio) -- si el resultado elegido exige una, no se puede
        # cumplir esa regla del arbol por esta via: se rechaza la fila en vez de guardar la
        # gestion sin compromiso en silencio.
        if resultado and resultado.requiere_fecha_pago:
            errores.append(
                f'el resultado "{resultado_nom}" requiere fecha de compromiso de pago; '
                'no se puede cargar por carga masiva de gestiones'
            )

        telefono = fila.get('telefono')
        phone_obj = None
        if telefono:
            digits = re.sub(r'\D', '', str(telefono))
            if digits:
                for p in Phone.objects.filter(lead=lead):
                    if re.sub(r'\D', '', p.phone_number or '') == digits:
                        phone_obj = p
                        break

        email = str(fila.get('email') or '').strip() or None
        if email and '@' not in email:
            email = None

        fecha_raw = fila.get('fecha_gestion')
        fecha_gestion = parse_fecha(fecha_raw)
        if fecha_raw not in (None, '') and not fecha_gestion:
            errores.append(f'fecha_gestion: "{fecha_raw}" no es una fecha válida')

        if errores:
            return None, errores
        return {
            'lead': lead, 'medio': medio, 'resultado': resultado,
            'user': get_user(fila.get('usuario')) or usuario,
            'comment': str(fila.get('comentario') or ''),
            'phone': phone_obj, 'email': email if not phone_obj else None,
            'fecha_gestion': fecha_gestion, 'hora_gestion': parse_hora(fila.get('hora_gestion')),
        }, []

    return validar_fila
