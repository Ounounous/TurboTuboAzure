from django.contrib import admin
from .models import Action


class ActionAdmin(admin.ModelAdmin):
    list_display = ('lead', 'action_type', 'result', 'user', 'phone', 'email', 'target', 'created_at')
    list_filter = ('action_type', 'result', 'user', 'created_at')
    search_fields = ('lead__op', 'phone__phone_number', 'email', 'target')


admin.site.register(Action, ActionAdmin)