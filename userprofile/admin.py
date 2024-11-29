from django.contrib import admin

from .models import Userprofile

admin.site.register(Userprofile)

class UserprofileAdmin(admin.ModelAdmin):
    list_display = ('user', 'user_type', 'active_team')
    list_filter = ('user_type', 'active_team')
    search_fields = ('user__username', 'user__email')
