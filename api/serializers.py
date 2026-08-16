from rest_framework import serializers

from actions.models import Medio, Resultado
from api.models import MapeoResultadoCampana
from cartera.models import Cartera, Subcartera
from demographics.models import IDDemographics, Phone
from lead.models import Lead


class SubcarteraSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subcartera
        fields = ('id', 'nombre', 'es_default')


class CarteraSerializer(serializers.ModelSerializer):
    subcarteras = SubcarteraSerializer(many=True, read_only=True)

    class Meta:
        model = Cartera
        fields = ('id', 'nombre', 'slug', 'arbol_tipo', 'subcarteras')


class MedioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Medio
        fields = ('id', 'nombre', 'canal', 'codigo', 'es_llamada', 'es_inbound', 'permite_manual')


class ResultadoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Resultado
        fields = (
            'id', 'nombre', 'codigo', 'tipo_contacto', 'contactabilidad',
            'crea_compromiso', 'requiere_fecha_pago', 'permite_manual',
        )


class PhoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = Phone
        fields = ('phone_number', 'phone_type', 'whatsapp_activo')


class DemographicsSerializer(serializers.ModelSerializer):
    """
    Solo teléfonos con phone_number_status=active -- un motor de campañas no debe recibir un
    número blacklisted/non-existent/out of service (ver decisión #2 y sección 05 del plan).

    get_principal_phones usa .all() (nunca .filter()): el filtro de "solo active" se aplica en el
    Prefetch de la vista (LeadViewSet.get_queryset), no aquí -- un .filter() sobre un M2M ya
    prefetched dispara una query nueva por cada lead (N+1), exactamente lo que este serializer
    existe para evitar en el listado paginado.
    """
    principal_phones = serializers.SerializerMethodField()

    class Meta:
        model = IDDemographics
        fields = ('principal_email', 'principal_email_status', 'principal_phones')

    def get_principal_phones(self, obj):
        return PhoneSerializer(obj.principal_phones.all(), many=True).data


class LeadListSerializer(serializers.ModelSerializer):
    """
    Incluye demografía (solo teléfono/correo en estado 'active') directamente en el listado
    paginado -- un motor de campañas necesita esto para armar audiencias reales sin tener que
    pedir el detalle de cada lead uno por uno (N+1). Sin N+1 de por sí: requiere que la vista
    traiga iddemographics_set y su principal_phones ya PREFETCHED (ver LeadViewSet.get_queryset),
    porque get_demografia() solo lee lo que ya está en memoria, nunca dispara una query nueva.
    """
    subcartera = serializers.CharField(source='subcartera.nombre', read_only=True)
    cartera = serializers.CharField(source='subcartera.cartera.nombre', read_only=True)
    demografia = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = (
            'id', 'op', 'name', 'subcartera', 'cartera', 'status', 'status_historico',
            'saldo_insoluto', 'saldo_deuda', 'cuotas_atrasadas', 'activo', 'demografia',
        )

    def get_demografia(self, obj):
        id_demo = obj.iddemographics_set.all()[0] if obj.iddemographics_set.all() else None
        if not id_demo:
            return None
        return DemographicsSerializer(id_demo).data


class LeadDetailSerializer(LeadListSerializer):
    class Meta(LeadListSerializer.Meta):
        fields = LeadListSerializer.Meta.fields + ('valor_cuota', 'tipo_cobranza')


class EventoWebhookSerializer(serializers.Serializer):
    """Mensaje 'evento' del Contrato API v1, sección 1.2 -- valida forma, no contenido de negocio
    (op existente, mapeo configurado, etc. se resuelven en el worker, no aquí)."""
    tipo = serializers.ChoiceField(choices=['evento'])
    event_id = serializers.CharField(max_length=64)
    op = serializers.CharField(max_length=16)
    target = serializers.ChoiceField(choices=['principal', 'aval'], required=False, default='principal')
    canal = serializers.ChoiceField(choices=[c for c, _ in MapeoResultadoCampana.CANALES])
    resultado = serializers.ChoiceField(choices=[r for r, _ in MapeoResultadoCampana.RESULTADOS_CORTOS])
    ocurrido_at = serializers.DateTimeField()
