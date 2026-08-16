from django.contrib import admin, messages

from .models import ApiClient, MapeoResultadoCampana, WebhookEventoJob


@admin.register(ApiClient)
class ApiClientAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'key_prefix', 'activo', 'tiene_hmac', 'created_at', 'last_used_at')
    list_filter = ('activo',)
    search_fields = ('nombre',)
    filter_horizontal = ('carteras',)
    readonly_fields = ('key_hash', 'key_prefix', 'created_at', 'last_used_at')
    fields = ('nombre', 'activo', 'carteras', 'key_hash', 'key_prefix', 'created_at', 'last_used_at')
    actions = ['generar_hmac_secret_action']

    def tiene_hmac(self, obj):
        return bool(obj.hmac_secret_encrypted)
    tiene_hmac.boolean = True
    tiene_hmac.short_description = 'HMAC configurado'

    def save_model(self, request, obj, form, change):
        if not change:
            # La key en texto plano solo existe en este momento -- se muestra una vez en el
            # mensaje de éxito del admin y nunca se vuelve a poder recuperar (mismo criterio
            # que un password: solo se guarda el hash).
            carteras = form.cleaned_data.get('carteras')
            nuevo, raw_key = ApiClient.generar(nombre=obj.nombre, carteras=carteras)
            obj.pk = nuevo.pk
            messages.warning(
                request,
                f'API key generada para "{obj.nombre}" (se muestra una sola vez, cópiala ahora): {raw_key}',
            )
        else:
            super().save_model(request, obj, form, change)

    @admin.action(description='Generar/regenerar secreto HMAC (solo webhook de escritura)')
    def generar_hmac_secret_action(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, 'Selecciona exactamente un cliente para generar su secreto.', level='error')
            return
        cliente = queryset.first()
        raw = cliente.generar_hmac_secret()
        messages.warning(
            request,
            f'Secreto HMAC generado para "{cliente.nombre}" (se muestra una sola vez, cópialo ahora): {raw}',
        )


@admin.register(MapeoResultadoCampana)
class MapeoResultadoCampanaAdmin(admin.ModelAdmin):
    list_display = ('cartera', 'canal', 'resultado_corto', 'medio', 'resultado')
    list_filter = ('cartera', 'canal')
    search_fields = ('cartera__nombre',)
    autocomplete_fields = ('medio', 'resultado')


@admin.register(WebhookEventoJob)
class WebhookEventoJobAdmin(admin.ModelAdmin):
    list_display = ('event_id', 'cliente', 'estado', 'created_at', 'finished_at')
    list_filter = ('estado', 'cliente')
    search_fields = ('event_id',)
    readonly_fields = ('event_id', 'cliente', 'payload', 'estado', 'action', 'detalle', 'created_at', 'finished_at')
