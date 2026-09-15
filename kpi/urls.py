from django.urls import path

from kpi.views import (
    KPIAssignmentCreateView,
    KPIAssignmentListView,
    KPICorrectionDecideView,
    KPICorrectionRequestCreateView,
    KPIDefinitionCreateView,
    KPIDefinitionEditView,
    KPIDefinitionListView,
    KPIEvaluationView,
    KPIPeriodCalculateView,
    KPIPeriodCloseView,
    KPIPeriodCreateView,
    KPIPeriodDetailView,
    KPIPeriodHRVerifyView,
    KPIPeriodListView,
    KPIPeriodRectorApproveView,
    KPIPeriodRectorRejectView,
    KPIPeriodRectorReviewView,
    KPIPeriodRectorSignView,
    KPIPeriodSubmitRectorView,
    PerformanceDashboardView,
)

app_name = 'kpi'

urlpatterns = [
    path('', PerformanceDashboardView.as_view(), name='dashboard'),
    path('definitions/', KPIDefinitionListView.as_view(), name='definition_list'),
    path('definitions/create/', KPIDefinitionCreateView.as_view(), name='definition_create'),
    path('definitions/<uuid:pk>/edit/', KPIDefinitionEditView.as_view(), name='definition_edit'),
    path('periods/', KPIPeriodListView.as_view(), name='period_list'),
    path('periods/create/', KPIPeriodCreateView.as_view(), name='period_create'),
    path('periods/<uuid:pk>/', KPIPeriodDetailView.as_view(), name='period_detail'),
    path('periods/<uuid:pk>/calculate/', KPIPeriodCalculateView.as_view(), name='period_calculate'),
    path('periods/<uuid:pk>/hr-verify/', KPIPeriodHRVerifyView.as_view(), name='period_hr_verify'),
    path('periods/<uuid:pk>/submit-rector/', KPIPeriodSubmitRectorView.as_view(), name='period_submit_rector'),
    path('periods/<uuid:pk>/rector-review/', KPIPeriodRectorReviewView.as_view(), name='period_rector_review'),
    path('periods/<uuid:pk>/rector-approve/', KPIPeriodRectorApproveView.as_view(), name='period_rector_approve'),
    path('periods/<uuid:pk>/rector-reject/', KPIPeriodRectorRejectView.as_view(), name='period_rector_reject'),
    path('periods/<uuid:pk>/rector-sign/', KPIPeriodRectorSignView.as_view(), name='period_rector_sign'),
    path('periods/<uuid:pk>/close/', KPIPeriodCloseView.as_view(), name='period_close'),
    path('assignments/', KPIAssignmentListView.as_view(), name='assignment_list'),
    path('assignments/create/', KPIAssignmentCreateView.as_view(), name='assignment_create'),
    path('assignments/<uuid:pk>/evaluate/', KPIEvaluationView.as_view(), name='evaluate'),
    path('results/<uuid:result_id>/correction/', KPICorrectionRequestCreateView.as_view(), name='request_correction'),
    path('corrections/<uuid:pk>/decide/', KPICorrectionDecideView.as_view(), name='decide_correction'),
]
