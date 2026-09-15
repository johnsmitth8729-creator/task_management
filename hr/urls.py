from django.urls import path

from hr.views import (
    EmployeeCreateView,
    EmployeeEditView,
    EmployeeGradeCreateView,
    EmployeeGradeEditView,
    EmployeeGradeListView,
    EmployeeProfileView,
    EmployeeToggleStatusView,
    HRDepartmentOptionsAPIView,
    HROverviewView,
    HRPermissionConfigView,
)

app_name = 'hr'

urlpatterns = [
    path('', HROverviewView.as_view(), name='overview'),
    path('employees/create/', EmployeeCreateView.as_view(), name='employee_create'),
    path('employees/<uuid:pk>/', EmployeeProfileView.as_view(), name='employee_profile'),
    path('employees/<uuid:pk>/edit/', EmployeeEditView.as_view(), name='employee_edit'),
    path('employees/<uuid:pk>/toggle-status/', EmployeeToggleStatusView.as_view(), name='employee_toggle_status'),
    path('grades/', EmployeeGradeListView.as_view(), name='grade_list'),
    path('grades/create/', EmployeeGradeCreateView.as_view(), name='grade_create'),
    path('grades/<uuid:pk>/edit/', EmployeeGradeEditView.as_view(), name='grade_edit'),
    path('permissions/', HRPermissionConfigView.as_view(), name='permissions_config'),
    path('api/department-options/', HRDepartmentOptionsAPIView.as_view(), name='api_department_options'),
]

