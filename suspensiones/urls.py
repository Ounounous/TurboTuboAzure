from django.urls import path

from . import views

app_name = 'suspensiones'

urlpatterns = [
    path('', views.SuspensionesHomeView.as_view(), name='index'),
    path('bulk-upload/', views.BulkLifecycleUploadView.as_view(), name='bulk_upload'),
    path('leads/<int:pk>/accion/', views.LeadLifecycleActionView.as_view(), name='lead_accion'),
]
