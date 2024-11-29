from django.contrib import admin
from .models import IDItem, Phone, IDDemographics, AvalDemographics

class IDItemAdmin(admin.ModelAdmin):
    list_display = ('lead', 'item_type', 'patente', 'marca', 'modelo', 'año')
    search_fields = ('lead__name', 'item_type', 'patente', 'marca', 'modelo')

admin.site.register(IDItem)
admin.site.register(Phone)
admin.site.register(IDDemographics)
admin.site.register(AvalDemographics)