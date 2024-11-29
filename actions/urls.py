from django.urls import path
from . import views

app_name = 'actions'

urlpatterns = [
    path('', views.ActionIndexView.as_view(), name='index'),
    path('multistep/', views.MultiStepActionView.as_view(), name='multistep'),  # Entry point for multi-step
    path('multistep/<int:step>/', views.MultiStepActionView.as_view(), name='multistep_step'),  # Step-wise progression
    path('multistep/<int:step>/<int:lead_id>/', views.MultiStepActionView.as_view(), name='multistep_step_with_lead'),
    # Step-wise with lead
    path('create/<int:lead_id>/', views.ActionCreateView.as_view(), name='create'),
    path('<int:pk>/', views.ActionDetailView.as_view(), name='detail'),
    path('download/<str:scope>/', views.ActionDownloadExcelView.as_view(), name='download_actions'),
]