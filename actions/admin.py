from django.contrib import admin
from django.utils.html import format_html
from .models import Action, Medio, Resultado, PendingPbxCall, CallRecording, PaymentCommitment, Payment


class MedioAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'cartera', 'canal', 'codigo', 'es_llamada', 'es_inbound', 'permite_manual')
    list_filter = ('cartera', 'canal', 'es_llamada', 'es_inbound', 'permite_manual')
    list_editable = ('permite_manual',)


class ResultadoAdmin(admin.ModelAdmin):
    list_display = (
        'cartera', 'codigo', 'nombre', 'tipo_contacto', 'contactabilidad',
        'crea_compromiso', 'requiere_fecha_pago', 'efecto_pago',
        'efecto_demografia', 'desactiva_whatsapp', 'descarga_grabacion', 'actualizado_por',
    )
    list_filter = (
        'cartera', 'tipo_contacto', 'contactabilidad', 'efecto_pago',
        'efecto_demografia', 'desactiva_whatsapp', 'descarga_grabacion',
    )
    search_fields = ('nombre', 'codigo', 'cartera__nombre')
    list_select_related = ('cartera', 'actualizado_por')
    list_editable = ('descarga_grabacion', 'efecto_pago', 'efecto_demografia', 'desactiva_whatsapp')
    readonly_fields = ('actualizado_por',)

    def save_model(self, request, obj, form, change):
        obj.actualizado_por = request.user
        super().save_model(request, obj, form, change)


class ActionAdmin(admin.ModelAdmin):
    list_display = ('cartera', 'subcartera', 'op', 'medio', 'resultado', 'user', 'target', 'created_at')
    list_filter = ('medio', 'resultado', 'user', 'created_at')
    search_fields = ('lead__op', 'phone__phone_number', 'email', 'target')
    list_select_related = ('lead', 'subcartera', 'subcartera__cartera', 'medio', 'resultado')

    @admin.display(description='Cartera', ordering='subcartera__cartera__nombre')
    def cartera(self, obj):
        return obj.subcartera.cartera.nombre if obj.subcartera else '-'

    @admin.display(description='Subcartera', ordering='subcartera__nombre')
    def subcartera(self, obj):
        return obj.subcartera.nombre if obj.subcartera else '-'

    @admin.display(description='ID', ordering='op')
    def op(self, obj):
        return obj.op


class PendingPbxCallAdmin(admin.ModelAdmin):
    list_display = ('lead', 'user', 'destination', 'requested_at', 'resolved', 'attempts', 'action')
    list_filter = ('resolved', 'user')
    search_fields = ('lead__op', 'destination')


class CallRecordingAdmin(admin.ModelAdmin):
    list_display = (
        'cartera', 'subcartera', 'op', 'medio', 'resultado', 'user',
        'call_date', 'duration_seconds', 'retention_until', 'audio_link', 'created_at',
    )
    list_filter = ('lead__subcartera__cartera', 'user', 'call_date')
    search_fields = ('lead__op', 'cdr_id')
    list_select_related = ('lead', 'lead__subcartera', 'lead__subcartera__cartera', 'action__medio', 'action__resultado', 'user')

    @admin.display(description='Cartera', ordering='lead__subcartera__cartera__nombre')
    def cartera(self, obj):
        return obj.lead.subcartera.cartera.nombre

    @admin.display(description='Subcartera', ordering='lead__subcartera__nombre')
    def subcartera(self, obj):
        return obj.lead.subcartera.nombre

    @admin.display(description='ID', ordering='lead__op')
    def op(self, obj):
        return obj.lead.op

    @admin.display(description='Medio')
    def medio(self, obj):
        return obj.action.medio.nombre if obj.action else '-'

    @admin.display(description='Resultado')
    def resultado(self, obj):
        return obj.action.resultado.nombre if obj.action else '-'

    @admin.display(description='Audio')
    def audio_link(self, obj):
        if not obj.audio_file:
            return '-'
        return format_html('<a href="{}" target="_blank">Escuchar / Descargar</a>', obj.audio_file.url)


class PaymentCommitmentAdmin(admin.ModelAdmin):
    list_display = (
        'cartera', 'subcartera', 'op', 'fecha_compromiso', 'monto', 'vigente', 'motivo_retiro',
        'created_by', 'created_at',
    )
    list_filter = ('vigente', 'motivo_retiro', 'lead__subcartera__cartera', 'fecha_compromiso', 'created_by')
    search_fields = ('lead__op',)
    list_select_related = ('lead', 'subcartera', 'subcartera__cartera', 'created_by')

    @admin.display(description='Cartera', ordering='subcartera__cartera__nombre')
    def cartera(self, obj):
        return obj.subcartera.cartera.nombre

    @admin.display(description='Subcartera', ordering='subcartera__nombre')
    def subcartera(self, obj):
        return obj.subcartera.nombre

    @admin.display(description='ID', ordering='lead__op')
    def op(self, obj):
        return obj.lead.op


class PaymentAdmin(admin.ModelAdmin):
    list_display = ('cartera', 'subcartera', 'op', 'monto', 'fecha', 'tipo', 'comprobante_link', 'created_by', 'created_at')
    list_filter = ('subcartera__cartera', 'tipo', 'fecha', 'created_by')
    search_fields = ('lead__op',)
    list_select_related = ('lead', 'subcartera', 'subcartera__cartera', 'created_by')

    @admin.display(description='Cartera', ordering='subcartera__cartera__nombre')
    def cartera(self, obj):
        return obj.subcartera.cartera.nombre if obj.subcartera else '-'

    @admin.display(description='Subcartera', ordering='subcartera__nombre')
    def subcartera(self, obj):
        return obj.subcartera.nombre if obj.subcartera else '-'

    @admin.display(description='ID', ordering='lead__op')
    def op(self, obj):
        return obj.lead.op

    @admin.display(description='Comprobante')
    def comprobante_link(self, obj):
        if not obj.comprobante:
            return '-'
        return format_html('<a href="{}" target="_blank">Ver comprobante</a>', obj.comprobante.url)


admin.site.register(Action, ActionAdmin)
admin.site.register(Medio, MedioAdmin)
admin.site.register(Resultado, ResultadoAdmin)
admin.site.register(PendingPbxCall, PendingPbxCallAdmin)
admin.site.register(CallRecording, CallRecordingAdmin)
admin.site.register(PaymentCommitment, PaymentCommitmentAdmin)
admin.site.register(Payment, PaymentAdmin)
