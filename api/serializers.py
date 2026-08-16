from rest_framework import serializers

from actions.models import Medio, Resultado
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
    """
    principal_phones = serializers.SerializerMethodField()

    class Meta:
        model = IDDemographics
        fields = ('principal_email', 'principal_email_status', 'principal_phones')

    def get_principal_phones(self, obj):
        activos = obj.principal_phones.filter(phone_number_status=Phone.ACTIVE)
        return PhoneSerializer(activos, many=True).data


class LeadListSerializer(serializers.ModelSerializer):
    """Serializer liviano para el listado -- sin demografía (evita N+1 en /leads/)."""
    subcartera = serializers.CharField(source='subcartera.nombre', read_only=True)
    cartera = serializers.CharField(source='subcartera.cartera.nombre', read_only=True)

    class Meta:
        model = Lead
        fields = (
            'id', 'op', 'name', 'subcartera', 'cartera', 'status', 'status_historico',
            'saldo_insoluto', 'saldo_deuda', 'cuotas_atrasadas', 'activo',
        )


class LeadDetailSerializer(LeadListSerializer):
    demografia = serializers.SerializerMethodField()

    class Meta(LeadListSerializer.Meta):
        fields = LeadListSerializer.Meta.fields + ('valor_cuota', 'tipo_cobranza', 'demografia')

    def get_demografia(self, obj):
        id_demo = obj.iddemographics_set.first()
        if not id_demo:
            return None
        return DemographicsSerializer(id_demo).data
