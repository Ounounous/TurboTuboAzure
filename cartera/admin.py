from django.contrib import admin

from .models import Cartera, Subcartera


class SubcarteraInline(admin.TabularInline):
    model = Subcartera
    extra = 0


@admin.register(Cartera)
class CarteraAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'activo', 'lista_supervisores', 'created_by', 'created_at')
    prepopulated_fields = {'slug': ('nombre',)}
    filter_horizontal = ('supervisores',)
    inlines = [SubcarteraInline]

    @admin.display(description='Supervisores')
    def lista_supervisores(self, obj):
        return ', '.join(u.username for u in obj.supervisores.all()) or '—'


@admin.register(Subcartera)
class SubcarteraAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'cartera', 'es_default', 'created_at')
    list_filter = ('cartera',)
