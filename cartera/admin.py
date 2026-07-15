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
    list_display = ('nombre', 'cartera', 'es_default', 'created_at')
    list_filter = ('cartera',)
