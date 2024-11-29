from django.urls import path
from .views import UploadExcelFileView, AssignLeadsView

from . import views

app_name = 'leads'

urlpatterns = [
    path('', views.LeadListView.as_view(), name='list'),
    path('<int:pk>/', views.LeadDetailView.as_view(), name='detail'),
    path('<int:pk>/delete/', views.LeadDeleteView.as_view(), name='delete'),
    path('<int:pk>/edit/', views.LeadUpdateView.as_view(), name='edit'),
    path('<int:pk>/convert/', views.ConvertToClientView.as_view(), name='convert'),
    path('<int:pk>/add-comment/', views.AddCommentView.as_view(), name='add_comment'),
    path('<int:pk>/add-file/', views.AddFileView.as_view(), name='add_file'),
    path('add/', views.LeadCreateView.as_view(), name='add_lead'),
    path('upload_excel/', views.UploadExcelFileView.as_view(), name='upload-excel'),
    path('download_excel/', views.DownloadExcelView.as_view(), name='download-excel'),
    path('assign/', AssignLeadsView.as_view(), name='leads_assign'),
    path('status-changes/<str:period>/', views.status_changes_by_date, name='status-changes'),
]