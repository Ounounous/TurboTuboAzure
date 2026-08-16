from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import ApiClient


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """
    Header: X-API-Key: <key>

    No usa el modelo User de Django -- request.user queda AnonymousUser y request.auth es el
    ApiClient autenticado (el mismo patron que TokenAuthentication de DRF, adaptado a nuestro
    propio modelo en vez de un token generico).
    """

    def authenticate(self, request):
        raw_key = request.META.get('HTTP_X_API_KEY')
        if not raw_key:
            return None

        try:
            client = ApiClient.objects.get(key_hash=ApiClient.hash_key(raw_key), activo=True)
        except ApiClient.DoesNotExist:
            raise exceptions.AuthenticationFailed('API key inválida.')

        ApiClient.objects.filter(pk=client.pk).update(last_used_at=timezone.now())
        return (None, client)

    def authenticate_header(self, request):
        return 'X-API-Key'
