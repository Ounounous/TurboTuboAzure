from django.urls import path

from . import views

app_name = 'team'

urlpatterns = [
    path('', views.teams_list, name='list'),
    path('crear/', views.crear_equipo, name='crear'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/edit/', views.edit_team, name='edit'),
    path('<int:pk>/activate/', views.teams_activate, name='activate'),
]