import logging

from django.db.models import Prefetch
from rest_framework import permissions, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from actions.models import Medio, Resultado
from cartera.models import Cartera
from configuracion.models import AccessLog, registrar_acceso
from demographics.models import IDDemographics, Phone
from lead.models import Lead

from .hmac_signing import FirmaInvalida, verificar
from .serializers import (
    CarteraSerializer, EventoWebhookSerializer, LeadDetailSerializer, LeadListSerializer,
    MedioSerializer, ResultadoSerializer,
)

logger = logging.getLogger(__name__)


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

    cartera o subcartera son OBLIGATORIOS (excepto para retrieve, un lead puntual por id) --
    auditoría de riesgos, hallazgo 12: sin esto, un cliente con acceso a "todas las carteras"
    (ApiClient.carteras vacío) podía barrer la base entera con /leads/ sin filtros, cientos de
    páginas contra la misma base que sirve el dashboard de producción, sin réplica de lectura.

    Nunca escribe. Tanto el listado como el detalle incluyen demografía (solo teléfono/correo en
    estado 'active') -- un motor de campañas necesita el dato de contacto para armar una audiencia
    real, no solo para consultar un lead a la vez. Sin N+1: la demografía se trae con Prefetch,
    2 queries extra fijas por página (IDDemographics + Phone), sin importar cuántos leads traiga.
    """
    permission_classes = [HasApiKey]
    throttle_scope = 'api_lectura'

    def get_serializer_class(self):
        return LeadDetailSerializer if self.action == 'retrieve' else LeadListSerializer

    def get_queryset(self):
        params = self.request.query_params
        if self.action == 'list' and not params.get('cartera') and not params.get('subcartera'):
            raise ValidationError('Se requiere el parámetro "cartera" o "subcartera" -- /leads/ no admite listar sin filtro de cartera.')

        telefonos_activos = Prefetch(
            'principal_phones', queryset=Phone.objects.filter(phone_number_status=Phone.ACTIVE),
        )
        demografia = Prefetch(
            'iddemographics_set',
            queryset=IDDemographics.objects.prefetch_related(telefonos_activos),
        )
        qs = Lead.objects.filter(
            subcartera__cartera__in=self.carteras_permitidas(),
        ).select_related('subcartera', 'subcartera__cartera').prefetch_related(demografia)

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


class WebhookEventoView(APIView):
    """
    POST /api/1.0/webhooks/eventos/ -- Contrato API v1, sección 1.2 "Evento" (motor → TurboTubo).

    Encola en Celery y responde 202: nunca procesa el evento en el proceso web (Action.save()
    dispara compromiso + status + efecto demográfico + captura ML). Valida en el request:
    - Firma HMAC (X-Signature + X-Signature-Timestamp) contra el secreto del ApiClient --
      SIEMPRE, antes que cualquier otra cosa (ver nota de idempotencia abajo).
    - Idempotencia por event_id: un event_id repetido, con firma válida, responde 200 sin crear
      un job nuevo.
    Todo lo que depende de datos (op existe, mapeo configurado, freno demográfico) se resuelve en
    el worker -- este endpoint no toca Lead/Action/Resultado.
    """
    permission_classes = [HasApiKey]
    throttle_scope = 'api_lectura'

    def post(self, request, *args, **kwargs):
        from .models import WebhookEventoJob
        from .tasks import procesar_evento_webhook

        client = request.auth
        if not client.hmac_secret:
            return Response(
                {'detail': 'Este cliente no tiene un secreto HMAC configurado; no puede usar el webhook de escritura.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # request.body se captura ANTES de tocar request.data en cualquier forma: DRF/Django
        # levanta RawPostDataException si se accede a .body después de que el parser ya leyó el
        # stream (request.data lo dispara). El orden acá importa, no es cosmético.
        cuerpo_crudo = request.body
        event_id = request.data.get('event_id', '') if isinstance(request.data, dict) else ''

        # Firma ANTES que idempotencia (auditoría de riesgos, hallazgo 5): con el orden inverso,
        # cualquiera que solo tuviera la API key (sin HMAC) podía enumerar event_id y leer el
        # estado interno de procesamiento de un job sin firmar nada -- un oráculo de estado sobre
        # datos que nunca debieron ser visibles sin la firma. El motor legítimo reintenta el MISMO
        # event_id con una firma recién calculada (mismo secreto, timestamp actual) -- eso sigue
        # verificando correcto, así que mover esto no rompe reintentos reales.
        firma = request.META.get('HTTP_X_SIGNATURE', '')
        firma_ts = request.META.get('HTTP_X_SIGNATURE_TIMESTAMP', '')
        try:
            verificar(client.hmac_secret, event_id, firma_ts, cuerpo_crudo, firma)
        except FirmaInvalida as exc:
            logger.warning(f'WebhookEventoView: firma inválida de cliente "{client.nombre}" -- {exc}')
            return Response({'detail': str(exc)}, status=status.HTTP_401_UNAUTHORIZED)

        if event_id:
            existente = WebhookEventoJob.objects.filter(event_id=event_id).first()
            if existente:
                return Response({'ok': True, 'event_id': event_id, 'estado': existente.estado, 'duplicado': True})

        serializer = EventoWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # .data (no .validated_data): representación serializable a JSON -- validated_data trae
        # ocurrido_at como datetime de Python, que JSONField no puede guardar directo.
        data = serializer.data

        job = WebhookEventoJob.objects.create(event_id=event_id, cliente=client, payload=data)
        try:
            procesar_evento_webhook.delay(job.pk)
        except Exception:
            logger.exception(f'No se pudo encolar procesar_evento_webhook para job {job.pk}; queda pendiente.')

        return Response(
            {'ok': True, 'event_id': event_id, 'estado': job.estado},
            status=status.HTTP_202_ACCEPTED,
        )
