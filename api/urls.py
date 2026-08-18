from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('carteras', views.CarteraViewSet, basename='cartera')
router.register('leads', views.LeadViewSet, basename='lead')
router.register('medios', views.MedioViewSet, basename='medio')
router.register('resultados', views.ResultadoViewSet, basename='resultado')

urlpatterns = router.urls + [
    path('webhooks/eventos/', views.WebhookEventoView.as_view(), name='webhook_evento'),
]
