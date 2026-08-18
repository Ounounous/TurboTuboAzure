"""
Throttle por ApiClient, no por IP (auditoría de riesgos, hallazgo 4).

ScopedRateThrottle (DRF) usa request.user.pk como identidad si request.user está autenticado, y
cae a la IP (get_ident) en caso contrario. api.authentication.ApiKeyAuthentication retorna
deliberadamente (None, client) -- request.user queda AnonymousUser porque la API es máquina a
máquina, no de usuario Django -- así que el throttle SIEMPRE caía a la IP. Y como NUM_PROXIES no
está configurado, get_ident usa el valor crudo de X-Forwarded-For que manda el propio cliente:
bastaba con rotar ese header en cada request para obtener una clave de cache nueva cada vez y
evadir el límite por completo. Aquí la identidad es request.auth.pk (el ApiClient real,
verificado por hash de la key), que el cliente no puede falsificar.
"""
from rest_framework.throttling import ScopedRateThrottle


class ApiClientRateThrottle(ScopedRateThrottle):
    def get_cache_key(self, request, view):
        if not request.auth:
            return None  # sin ApiClient autenticado, HasApiKey ya rechaza la request antes de esto
        return self.cache_format % {
            'scope': self.scope,
            'ident': request.auth.pk,
        }
