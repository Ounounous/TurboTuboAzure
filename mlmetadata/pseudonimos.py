"""
Genera/resuelve los tokens opacos que reemplazan identidad real en la metadata (mlmetadata/
models.py). Los tokens son estables (siempre el mismo token para la misma cartera/lead/
cobrador) pero no reversibles fuera de las tablas *Pseudonimo de esta app -- si se borra la
cartera/lead/usuario real, se borra el mapeo (CASCADE) pero los eventos ya capturados quedan
con el token igual (es un CharField/UUIDField suelto, no un FK -- ver EventoBase).
"""
import secrets
import uuid

from .models import CarteraPseudonimo, CobradorPseudonimo, LeadPseudonimo


def _token_opaco(prefijo):
    # Aleatorio, sin relacion con orden de creacion (evita filtrar "esta cartera es la mas
    # antigua" a quien vea el dataset exportado).
    return f'{prefijo}-{secrets.token_hex(4).upper()}'


def cartera_token(cartera):
    obj, _ = CarteraPseudonimo.objects.get_or_create(
        cartera=cartera, defaults={'token': _token_opaco('Cartera')}
    )
    return obj.token


def lead_token(lead):
    obj, _ = LeadPseudonimo.objects.get_or_create(
        lead=lead, defaults={'token': uuid.uuid4()}
    )
    return obj.token


def cobrador_token(user):
    if not user:
        return None
    obj, _ = CobradorPseudonimo.objects.get_or_create(
        user=user, defaults={'token': _token_opaco('Cobrador')}
    )
    return obj.token
