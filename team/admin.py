from django.contrib import admin
from .models import Team, Plan


class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'supervisor', 'created_by', 'created_at')
    list_filter = ('supervisor', 'created_by')
    search_fields = ('name', 'supervisor__username', 'created_by__username')


admin.site.register(Team, TeamAdmin)
admin.site.register(Plan)