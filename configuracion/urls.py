from django.urls import path

from . import views

app_name = 'configuracion'

urlpatterns = [
    path('', views.ConfiguracionHomeView.as_view(), name='index'),
    path('usuarios-permisos/', views.UsuariosPermisosView.as_view(), name='usuarios_permisos'),
    path('retencion/', views.RetencionDatosView.as_view(), name='retencion'),
]
