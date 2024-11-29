from django.contrib import admin

from .models import Lead, Comment, LeadFile, LeadAssignment, StatusChangeLog

class StatusChangeLogAdmin(admin.ModelAdmin):
    list_display = ('lead', 'new_status', 'changed_by', 'timestamp')  # Ensure 'timestamp' is included

admin.site.register(Lead)
admin.site.register(Comment)
admin.site.register(LeadFile)
admin.site.register(LeadAssignment)
admin.site.register(StatusChangeLog, StatusChangeLogAdmin)
