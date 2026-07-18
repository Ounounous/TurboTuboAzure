from django.urls import path
from .views import (
    DemographicsIndexView, DownloadTemplateView, UploadIDItemView, UploadPhoneView,
    UploadIDDemographicsView, UploadAddressView, UploadAvalDemographicsView,
    PhoneStatusView, PhoneStatusBulkView, EmailStatusView, EmailStatusBulkView,
)

app_name = 'demographics'

urlpatterns = [
    path('', DemographicsIndexView.as_view(), name='index'),
    path('upload/iditem/', UploadIDItemView.as_view(), name='upload_iditem'),
    path('upload/phone/', UploadPhoneView.as_view(), name='upload_phone'),
    path('upload/iddemographics/', UploadIDDemographicsView.as_view(), name='upload_iddemographics'),
    path('upload/address/', UploadAddressView.as_view(), name='upload_address'),
    path('upload/aval_demographics/', UploadAvalDemographicsView.as_view(), name='upload_aval_demographics'),
    path('download-template/<str:form_type>/', DownloadTemplateView.as_view(), name='download_template'),
    # Estado de demografía
    path('estado/telefonos/', PhoneStatusView.as_view(), name='phone_status'),
    path('estado/telefonos/bulk/', PhoneStatusBulkView.as_view(), name='phone_status_bulk'),
    path('estado/correos/', EmailStatusView.as_view(), name='email_status'),
    path('estado/correos/bulk/', EmailStatusBulkView.as_view(), name='email_status_bulk'),
]