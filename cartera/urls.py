from django.urls import path

from . import views

app_name = 'cartera'

urlpatterns = [
    path('', views.CarteraListView.as_view(), name='list'),
    path('add/', views.CarteraCreateView.as_view(), name='add'),
    path('<int:pk>/', views.CarteraDetailView.as_view(), name='detail'),
    path('<int:pk>/delete/', views.CarteraDeleteView.as_view(), name='delete'),
    path('<int:pk>/asignar-arbol/', views.AsignarArbolView.as_view(), name='asignar_arbol'),
    path('<int:cartera_pk>/subcarteras/add/', views.SubcarteraCreateView.as_view(), name='add_subcartera'),
    path('<int:cartera_pk>/subcarteras/<int:pk>/', views.SubcarteraDetailView.as_view(), name='subcartera_detail'),
    path('<int:cartera_pk>/subcarteras/<int:pk>/eliminar/', views.SubcarteraDeleteView.as_view(), name='delete_subcartera'),
    path('<int:cartera_pk>/subcarteras/<int:pk>/marcar-default/', views.SubcarteraSetDefaultView.as_view(), name='set_default_subcartera'),
]
