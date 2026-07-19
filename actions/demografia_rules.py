"""
Reglas (revisadas con el usuario sobre los arboles de Galgo, Tanner y Nuevo Capital) que dicen
como el resultado de una gestion afecta al dato de contacto usado. Se usan tanto en los comandos
de importacion (reinstalaciones) como replicadas en la migracion de datos que siembra la base
actual. Fuente de verdad de la config demografica de cada Resultado.
"""
import unicodedata


def _norm(nombre):
    s = str(nombre or '').strip().upper()
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))


def efecto_demografia(nombre):
    """Devuelve '' | 'blacklist' | 'no_existe' | 'fuera_servicio' segun el nombre del resultado."""
    E = _norm(nombre)

    # La direccion no tiene estado en este alcance (aunque diga "no corresponde").
    if 'DIRECCION' in E:
        return ''

    # Blacklist: el dato es equivocado / no es del titular / correo invalido -> no volver a usar.
    if 'NO CORRESPONDE' in E or 'EQUIVOCAD' in E or ('INVALIDO' in E and ('EMAIL' in E or 'CORREO' in E)):
        return 'blacklist'

    # Fuera de servicio: existe pero no operativo.
    if 'FUERA DE SERVICIO' in E or 'NO DISPONIBLE' in E:
        return 'fuera_servicio'

    # Rebote de correo -> no existe. Rebote de SMS/carta/IVR/WhatsApp NO cambia el estado del
    # numero (sin accion); WhatsApp ademas se apaga aparte (ver desactiva_whatsapp).
    if 'EMAIL' in E and 'NO ENTREGADO' in E:
        return 'no_existe'

    return ''


def desactiva_whatsapp(nombre):
    """True si el resultado apaga WhatsApp del numero (sin cambiar su estado)."""
    E = _norm(nombre)
    return 'SIN WHATSAPP' in E or ('WHATSAPP' in E and 'NO ENTREGADO' in E)
