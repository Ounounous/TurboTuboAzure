from django.contrib import admin

from .models import RetentionSettings


@admin.register(RetentionSettings)
class RetentionSettingsAdmin(admin.ModelAdmin):
    list_display = ('dias_purga_terminado', 'dias_purga_desasignado', 'updated_by', 'updated_at')

    def has_add_permission(self, request):
        return not RetentionSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
