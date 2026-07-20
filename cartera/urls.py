from django.urls import path

from . import views

app_name = 'cartera'

urlpatterns = [
    path('', views.CarteraListView.as_view(), name='list'),
    path('add/', views.CarteraCreateView.as_view(), name='add'),
    path('<int:pk>/', views.CarteraDetailView.as_view(), name='detail'),
    path('<int:pk>/delete/', views.CarteraDeleteView.as_view(), name='delete'),
    path('<int:cartera_pk>/subcarteras/add/', views.SubcarteraCreateView.as_view(), name='add_subcartera'),
]
