from django.contrib import admin

from .models import CicloVidaEvento, GestionEvento, PagoEvento


@admin.register(GestionEvento)
class GestionEventoAdmin(admin.ModelAdmin):
    list_display = (
        'cartera_token', 'lead_token', 'canal', 'contactabilidad', 'efecto_pago',
        'status_antes', 'status_despues', 'created_at', 'exportado_at',
    )
    list_filter = ('cartera_token', 'canal', 'contactabilidad', 'status_despues')
    search_fields = ('cartera_token', 'lead_token')
    date_hierarchy = 'created_at'


@admin.register(PagoEvento)
class PagoEventoAdmin(admin.ModelAdmin):
    list_display = ('cartera_token', 'lead_token', 'monto', 'tipo', 'dias_vs_compromiso', 'created_at', 'exportado_at')
    list_filter = ('cartera_token', 'tipo')
    search_fields = ('cartera_token', 'lead_token')
    date_hierarchy = 'created_at'


@admin.register(CicloVidaEvento)
class CicloVidaEventoAdmin(admin.ModelAdmin):
    list_display = ('cartera_token', 'lead_token', 'tipo_transicion', 'created_at', 'exportado_at')
    list_filter = ('cartera_token', 'tipo_transicion')
    search_fields = ('cartera_token', 'lead_token')
    date_hierarchy = 'created_at'
