from django.urls import path

from . import views

app_name = 'configuracion'

urlpatterns = [
    path('', views.ConfiguracionHomeView.as_view(), name='index'),
    path('usuarios-permisos/', views.UsuariosPermisosView.as_view(), name='usuarios_permisos'),
    path('equipo/', views.EquipoView.as_view(), name='equipo'),
    path('retencion/', views.RetencionDatosView.as_view(), name='retencion'),
    path('registros/', views.RegistrosAccionesView.as_view(), name='registros'),
    path('cargas-masivas/', views.CargasMasivasView.as_view(), name='cargas_masivas'),
]
