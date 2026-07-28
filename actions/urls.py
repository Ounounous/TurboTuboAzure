from django.urls import path
from . import views

app_name = 'actions'

urlpatterns = [
    path('', views.ActionIndexView.as_view(), name='index'),
    path('multistep/', views.MultiStepActionView.as_view(), name='multistep'),  # Entry point for multi-step
    path('multistep/<int:step>/', views.MultiStepActionView.as_view(), name='multistep_step'),  # Step-wise progression
    path('multistep/<int:step>/<int:lead_id>/', views.MultiStepActionView.as_view(), name='multistep_step_with_lead'),
    # Step-wise with lead
    path('cancel/<int:lead_id>/', views.CancelActionView.as_view(), name='cancel'),
    path('popup-close/', views.PopupCloseView.as_view(), name='popup_close'),
    path('pbx/call/', views.OriginatePbxCallView.as_view(), name='pbx_call'),
    path('grabaciones/', views.RecordingListView.as_view(), name='recordings_list'),
    path('grabaciones/exportar/', views.RecordingsExportZipView.as_view(), name='recordings_export'),
    path('grabaciones/sincronizar/', views.SyncRecordingsNowView.as_view(), name='recordings_sync'),
    path('create/<int:lead_id>/', views.ActionCreateView.as_view(), name='create'),
    path('<int:pk>/', views.ActionDetailView.as_view(), name='detail'),
    path('download/<str:scope>/', views.ActionDownloadExcelView.as_view(), name='download_actions'),
    path('reporte-tanner/', views.TannerReportView.as_view(), name='tanner_report'),
    path('reporte-nuevocapital/', views.NuevoCapitalReportView.as_view(), name='nuevocapital_report'),
    path('compromisos/', views.PaymentCommitmentListView.as_view(), name='commitments_list'),
    path('compromisos/exportar/', views.PaymentCommitmentExportExcelView.as_view(), name='commitments_export'),
    path('carga-masiva/', views.BulkActionUploadView.as_view(), name='bulk_upload'),
    path('carga-masiva/plantilla/', views.BulkActionTemplateView.as_view(), name='bulk_template'),
    path('pagos/', views.PaymentListView.as_view(), name='payments_list'),
    path('pagos/nuevo/<int:lead_id>/', views.PaymentCreateView.as_view(), name='payment_create'),
]