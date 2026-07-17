from django.urls import path

from . import views

app_name = 'judicial'

urlpatterns = [
    path('', views.JudicialHomeView.as_view(), name='index'),
    path('toggle/', views.ToggleJudicialInfoView.as_view(), name='toggle'),
    path('bulk-upload/', views.BulkUploadEstadoJudicialView.as_view(), name='bulk_upload'),
    path('leads/<int:lead_id>/estado/', views.UpdateLeadEstadoJudicialView.as_view(), name='update_estado'),
]
