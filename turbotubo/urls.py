# from schema_graph.views import Schema #

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include

from core.views import index, about, health_check
from userprofile.forms import LoginForm

urlpatterns = [
    path('', index, name='index'),
    path('dashboard/actions/', include('actions.urls')),
    path('dashboard/leads/', include('lead.urls')),
    path('dashboard/clients/', include('client.urls')),
    path('dashboard/teams/', include('team.urls')),
    path('dashboard', include('userprofile.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('demographics/', include('demographics.urls', namespace='demographics')),
    path('about/', about, name='about'),
    path('log-in/', auth_views.LoginView.as_view(template_name='userprofile/login.html', authentication_form=LoginForm), name='login'),
    path('log-out/', auth_views.LogoutView.as_view(), name='logout'),
    path('admin/', admin.site.urls),
    path('health/', health_check, name='health_check'),
#    path('schema/', Schema.as_view()), #
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
