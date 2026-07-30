"""
Limite de concurrencia para operaciones pesadas (exports Excel grandes, etc.), para que un par de
descargas simultaneas no acaparen los workers web y dejen lento el ingreso de gestiones.

Usa cache.add() de Redis, que es atomico (devuelve True solo si la clave no existia): se reparten
N "cupos"; si todos estan tomados, se rechaza con SinCupo y el usuario reintenta en un momento.
Degrada ABIERTO: si el cache no responde, deja pasar la operacion (mejor una descarga sin limitar
que caerse porque Redis no esta).
"""
from contextlib import contextmanager
from functools import wraps

from django.core.cache import cache


class SinCupo(Exception):
    """No hay cupo libre para esta operacion pesada en este momento."""


@contextmanager
def limite_concurrencia(prefijo, slots=2, timeout=300):
    adquirido = None
    for i in range(slots):
        clave = f'cc:{prefijo}:{i}'
        try:
            if cache.add(clave, 1, timeout):
                adquirido = clave
                break
        except Exception:
            # Cache caido: no bloqueamos la operacion.
            adquirido = None
            break
    else:
        # El for termino sin break -> todos los cupos estaban tomados.
        raise SinCupo()

    try:
        yield
    finally:
        if adquirido:
            try:
                cache.delete(adquirido)
            except Exception:
                pass


def con_limite_concurrencia(prefijo, slots=2, timeout=300):
    """Decorador para metodos de vista (get/post) que hacen trabajo pesado sincronico. Si no hay
    cupo, responde 429 en vez de dejar que se acumulen y saturen los workers web."""
    def deco(viewfunc):
        @wraps(viewfunc)
        def wrapper(self, request, *args, **kwargs):
            try:
                with limite_concurrencia(prefijo, slots, timeout):
                    return viewfunc(self, request, *args, **kwargs)
            except SinCupo:
                from django.http import JsonResponse
                return JsonResponse(
                    {"error": "Hay varias descargas pesadas en curso. Intenta de nuevo en un momento."},
                    status=429,
                )
        return wrapper
    return deco
