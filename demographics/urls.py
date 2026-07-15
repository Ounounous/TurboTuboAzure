from django.urls import path
from .views import (
    DemographicsIndexView, DownloadTemplateView, UploadIDItemView, UploadPhoneView,
    UploadIDDemographicsView, UploadAddressView, UploadAvalDemographicsView,
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
]