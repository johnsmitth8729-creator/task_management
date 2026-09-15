from django.urls import path
from operations import views

app_name = 'operations'

urlpatterns = [
    # University Service Catalog & Applications
    path('services/', views.ServiceCatalogView.as_view(), name='service_catalog'),
    path('services/apply/', views.RequestSubmitView.as_view(), name='request_apply_direct'),
    path('services/apply/<uuid:type_id>/', views.RequestSubmitView.as_view(), name='request_apply'),
    path('my-requests/', views.MyRequestsListView.as_view(), name='my_requests'),
    path('requests/approval-queue/', views.RequestApprovalQueueView.as_view(), name='approval_queue'),
    path('requests/<uuid:pk>/', views.RequestDetailView.as_view(), name='request_detail'),
    path('requests/<uuid:pk>/cancel/', views.RequestCancelView.as_view(), name='request_cancel'),

    # Promulgated Documents & Rector Orders Registry
    path('documents/', views.DocumentListView.as_view(), name='document_list'),
    path('documents/new/', views.DocumentCreateView.as_view(), name='document_create'),
    path('documents/<uuid:pk>/', views.DocumentDetailView.as_view(), name='document_detail'),
    path('documents/<uuid:pk>/version/', views.DocumentVersionUploadView.as_view(), name='document_version_upload'),
]
