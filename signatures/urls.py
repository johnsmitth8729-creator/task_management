from django.urls import path
from signatures import views

urlpatterns = [
    path('tasks/<uuid:task_id>/sign/', views.SignTaskView.as_view(), name='sign_task'),
    path('verify/<str:verification_id>/', views.public_verification_view, name='public_verify'),
    path('signatures/<str:verification_id>/qr/', views.signature_qr_view, name='signature_qr'),
    path('signatures/<str:verification_id>/pdf/', views.download_signed_pdf_view, name='signature_pdf'),
    path('signatures/<uuid:signature_id>/revoke/', views.RevokeSignatureView.as_view(), name='revoke_signature'),
    path('api/tasks/<uuid:task_id>/sign/', views.api_sign_task, name='api_sign_task'),
    path('api/verify/<str:verification_id>/', views.api_verify_signature, name='api_verify_signature'),
]
