from django.contrib import admin, messages

from .models import ApiClient


@admin.register(ApiClient)
class ApiClientAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'key_prefix', 'activo', 'created_at', 'last_used_at')
    list_filter = ('activo',)
    search_fields = ('nombre',)
    filter_horizontal = ('carteras',)
    readonly_fields = ('key_hash', 'key_prefix', 'created_at', 'last_used_at')
    fields = ('nombre', 'activo', 'carteras', 'key_hash', 'key_prefix', 'created_at', 'last_used_at')

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
