from django.urls import path

from . import views

app_name = 'userprofile'

urlpatterns = [
    path('myaccount/', views.myaccount, name='myaccount'),
    path('cambiar-password/', views.cambiar_password, name='cambiar_password'),
    # El registro publico (/sign-up/) se elimino a proposito: los usuarios los crea un admin
    # desde Configuracion -> Usuarios (con clave temporal). Ver userprofile.views.
]

