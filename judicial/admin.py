from django.contrib import admin

from .models import JudicialSettings


@admin.register(JudicialSettings)
class JudicialSettingsAdmin(admin.ModelAdmin):
    list_display = ('mostrar_info_judicial', 'updated_by', 'updated_at')

    def has_add_permission(self, request):
        return not JudicialSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
