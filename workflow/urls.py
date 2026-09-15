from django.urls import path

from workflow.views import (
    AcceptAssignmentView,
    AddNoteView,
    AssignmentDetailView,
    DeptHeadApproveSubmissionView,
    DeptHeadAssignEmployeesView,
    DeptHeadDashboardView,
    DeptHeadFirstApprovalQueueView,
    DeptHeadRejectSubmissionView,
    DeptHeadSubmissionDetailView,
    DeptHeadTaskDetailView,
    DeptHeadTaskListView,
    EmployeeDashboardView,
    EmployeeFirstApprovalView,
    EmployeeIncomingView,
    EmployeeInProgressView,
    EmployeeSecondApprovalView,
    ManagementFinalApproveView,
    ManagementRejectView,
    ManagementSecondApprovalDashboardView,
    ManagementSecondApprovalDetailView,
    RejectedTasksView,
    StartReworkView,
    SubmitAssignmentView,
    SuccessfullyCompletedTasksView,
    TaskDeadlineExtensionView,
    UpdateProgressView,
    WorkflowApprovalsHubView,
    WorkflowDashboardRedirectView,
)

urlpatterns = [
    # Unified approvals hub (edo.ijro.uz style)
    path('workflow/approvals/', WorkflowApprovalsHubView.as_view(), name='workflow_approvals_hub'),

    # Role-based redirect
    path('workflow/', WorkflowDashboardRedirectView.as_view(), name='workflow_dashboard'),

    # Employee workflow
    path('workflow/employee/', EmployeeDashboardView.as_view(), name='employee_dashboard'),
    path('workflow/employee/incoming/', EmployeeIncomingView.as_view(), name='employee_incoming'),
    path('workflow/employee/in-progress/', EmployeeInProgressView.as_view(), name='employee_inprogress'),
    path('workflow/employee/first-approval/', EmployeeFirstApprovalView.as_view(), name='employee_first_approval'),
    path('workflow/employee/second-approval/', EmployeeSecondApprovalView.as_view(), name='employee_second_approval'),

    # Assignment actions
    path('workflow/assignments/<uuid:pk>/', AssignmentDetailView.as_view(), name='assignment_detail'),
    path('workflow/assignments/<uuid:pk>/accept/', AcceptAssignmentView.as_view(), name='assignment_accept'),
    path('workflow/assignments/<uuid:pk>/progress/', UpdateProgressView.as_view(), name='assignment_progress'),
    path('workflow/assignments/<uuid:pk>/notes/', AddNoteView.as_view(), name='assignment_add_note'),
    path('workflow/assignments/<uuid:pk>/submit/', SubmitAssignmentView.as_view(), name='assignment_submit'),
    path('workflow/assignments/<uuid:pk>/rework/', StartReworkView.as_view(), name='assignment_rework'),

    # Department Head workflow
    path('workflow/dept/', DeptHeadDashboardView.as_view(), name='dept_dashboard'),
    path('workflow/dept/tasks/', DeptHeadTaskListView.as_view(), name='dept_task_list'),
    path('workflow/dept/tasks/<uuid:pk>/', DeptHeadTaskDetailView.as_view(), name='dept_task_detail'),
    path('workflow/dept/tasks/<uuid:pk>/assign/', DeptHeadAssignEmployeesView.as_view(), name='dept_assign_employees'),
    path('workflow/dept/first-approval/', DeptHeadFirstApprovalQueueView.as_view(), name='dept_first_approval'),
    path('workflow/dept/submissions/<uuid:pk>/', DeptHeadSubmissionDetailView.as_view(), name='submission_detail'),
    path('workflow/dept/submissions/<uuid:pk>/approve/', DeptHeadApproveSubmissionView.as_view(), name='dept_approve_submission'),
    path('workflow/dept/submissions/<uuid:pk>/reject/', DeptHeadRejectSubmissionView.as_view(), name='dept_reject_submission'),

    # Management Second & Final Approval workflow
    path('workflow/management/second-approval/', ManagementSecondApprovalDashboardView.as_view(), name='management_second_approval'),
    path('workflow/management/second-approval/<uuid:pk>/', ManagementSecondApprovalDetailView.as_view(), name='management_second_approval_detail'),
    path('workflow/management/second-approval/<uuid:pk>/approve/', ManagementFinalApproveView.as_view(), name='management_final_approve'),
    path('workflow/management/second-approval/<uuid:pk>/reject/', ManagementRejectView.as_view(), name='management_reject'),
    path('workflow/tasks/<uuid:pk>/extend-deadline/', TaskDeadlineExtensionView.as_view(), name='task_extend_deadline'),

    # Completed & Rejected views
    path('workflow/completed/', SuccessfullyCompletedTasksView.as_view(), name='completed_tasks'),
    path('workflow/rejected/', RejectedTasksView.as_view(), name='rejected_tasks'),
]

