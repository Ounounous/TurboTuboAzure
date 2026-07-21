from django.contrib import admin
from .models import Team, Plan


class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_by', 'created_at')
    list_filter = ('created_by',)
    search_fields = ('name', 'created_by__username')


admin.site.register(Team, TeamAdmin)
admin.site.register(Plan)