from rest_framework import permissions, viewsets
from rest_framework.exceptions import NotFound

from actions.models import Medio, Resultado
from cartera.models import Cartera
from configuracion.models import AccessLog, registrar_acceso
from lead.models import Lead

from .serializers import (
    CarteraSerializer, LeadDetailSerializer, LeadListSerializer, MedioSerializer,
    ResultadoSerializer,
)


class HasApiKey(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.auth is not None


class ClienteCarteraScopedMixin:
    """Filtra el queryset a las carteras que el ApiClient autenticado puede ver."""

    def carteras_permitidas(self):
        client = self.request.auth
        if not client.carteras.exists():
            return Cartera.objects.filter(activo=True)
        return client.carteras.filter(activo=True)


class CarteraViewSet(ClienteCarteraScopedMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = CarteraSerializer
    permission_classes = [HasApiKey]
    throttle_scope = 'api_lectura'

    def get_queryset(self):
        return self.carteras_permitidas().prefetch_related('subcarteras')


class MedioViewSet(ClienteCarteraScopedMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = MedioSerializer
    permission_classes = [HasApiKey]
    throttle_scope = 'api_lectura'

    def get_queryset(self):
        qs = Medio.objects.filter(cartera__in=self.carteras_permitidas())
        cartera_id = self.request.query_params.get('cartera')
        if cartera_id:
            qs = qs.filter(cartera_id=cartera_id)
        return qs.select_related('cartera')


class ResultadoViewSet(ClienteCarteraScopedMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = ResultadoSerializer
    permission_classes = [HasApiKey]
    throttle_scope = 'api_lectura'

    def get_queryset(self):
        qs = Resultado.objects.filter(cartera__in=self.carteras_permitidas())
        cartera_id = self.request.query_params.get('cartera')
        if cartera_id:
            qs = qs.filter(cartera_id=cartera_id)
        return qs.select_related('cartera')


class LeadViewSet(ClienteCarteraScopedMixin, viewsets.ReadOnlyModelViewSet):
    """
    GET /api/1.0/leads/?cartera=<id>&subcartera=<id>&status=<status>&op=<op>

    Nunca escribe. El detalle incluye demografía (solo teléfonos/correo en estado 'active');
    el listado no, para no traer N+1 de teléfonos en cada página.
    """
    permission_classes = [HasApiKey]
    throttle_scope = 'api_lectura'

    def get_serializer_class(self):
        return LeadDetailSerializer if self.action == 'retrieve' else LeadListSerializer

    def get_queryset(self):
        qs = Lead.objects.filter(
            subcartera__cartera__in=self.carteras_permitidas(),
        ).select_related('subcartera', 'subcartera__cartera')

        params = self.request.query_params
        if params.get('cartera'):
            qs = qs.filter(subcartera__cartera_id=params['cartera'])
        if params.get('subcartera'):
            qs = qs.filter(subcartera_id=params['subcartera'])
        if params.get('status'):
            qs = qs.filter(status=params['status'])
        if params.get('op'):
            qs = qs.filter(op=params['op'])
        return qs.order_by('id')

    def get_object(self):
        try:
            obj = super().get_object()
        except Lead.DoesNotExist:
            raise NotFound('Lead no encontrado o fuera del alcance de este cliente.')
        registrar_acceso(None, AccessLog.VER_FICHA, lead=obj, detail=f'API ({self.request.auth.nombre})')
        return obj
