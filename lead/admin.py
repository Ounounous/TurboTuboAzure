from django.contrib import admin

from .models import Lead, LeadFile, LeadAssignment, StatusChangeLog

class StatusChangeLogAdmin(admin.ModelAdmin):
    list_display = ('lead', 'new_status', 'changed_by', 'timestamp')  # Ensure 'timestamp' is included


class LeadAdmin(admin.ModelAdmin):
    # op/name como texto; rut es IntegerField -- el admin lo castea a int y, si el termino de
    # busqueda no es numerico, simplemente omite ese campo del OR (no rompe la busqueda por texto).
    search_fields = ('op', 'name', 'rut')
    list_display = ('op', 'name', 'rut', 'dv', 'subcartera', 'status', 'assigned_to')
    list_filter = ('subcartera__cartera', 'subcartera', 'status', 'activo')


admin.site.register(Lead, LeadAdmin)
admin.site.register(LeadFile)
admin.site.register(LeadAssignment)
admin.site.register(StatusChangeLog, StatusChangeLogAdmin)
