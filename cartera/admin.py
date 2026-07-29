from django.contrib import admin

from .models import Cartera, Subcartera


class SubcarteraInline(admin.TabularInline):
    model = Subcartera
    extra = 0


@admin.register(Cartera)
class CarteraAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'activo', 'created_by', 'created_at')
    prepopulated_fields = {'slug': ('nombre',)}
    inlines = [SubcarteraInline]


@admin.register(Subcartera)
class SubcarteraAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'cartera', 'es_default', 'lista_supervisores', 'created_at')
    list_filter = ('cartera',)
    filter_horizontal = ('supervisores',)

    @admin.display(description='Supervisores')
    def lista_supervisores(self, obj):
        return ', '.join(u.username for u in obj.supervisores.all()) or '—'
