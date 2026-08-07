from django.contrib import admin
from .models import IDItem, Phone, IDDemographics, AvalDemographics, ContactExportJob

class IDItemAdmin(admin.ModelAdmin):
    list_display = ('lead', 'item_type', 'patente', 'marca', 'modelo', 'año')
    search_fields = ('lead__name', 'item_type', 'patente', 'marca', 'modelo')

admin.site.register(IDItem)
admin.site.register(Phone)
admin.site.register(IDDemographics)
admin.site.register(AvalDemographics)


@admin.register(ContactExportJob)
class ContactExportJobAdmin(admin.ModelAdmin):
    """Registrado sobre todo para poder borrar a mano un job que quedo atascado (ej. un mensaje
    de Celery perdido en un deploy) sin necesitar acceso al servidor."""
    list_display = ('id', 'tipo', 'estado', 'solicitado_por', 'total_filas', 'created_at', 'finished_at')
    list_filter = ('tipo', 'estado')
    search_fields = ('solicitado_por__username',)
    readonly_fields = ('solicitado_por', 'tipo', 'filtros', 'archivo', 'total_filas', 'mensaje', 'created_at', 'finished_at')