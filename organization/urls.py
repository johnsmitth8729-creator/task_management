from django.urls import path

from .views import (
    DepartmentAssignHeadView,
    DepartmentCreateView,
    DepartmentDetailView,
    DepartmentListView,
    DepartmentToggleActiveView,
    DepartmentUpdateView,
    OrganizationOverviewView,
    PositionCreateView,
    PositionListView,
    PositionToggleActiveView,
    PositionUpdateView,
    ViceRectorResponsibilityCreateView,
    ViceRectorResponsibilityDeleteView,
    ViceRectorResponsibilityListView,
)

urlpatterns = [
    path('organization/', OrganizationOverviewView.as_view(), name='organization_overview'),
    # Departments
    path('departments/', DepartmentListView.as_view(), name='department_list'),
    path('departments/create/', DepartmentCreateView.as_view(), name='department_create'),
    path('departments/<uuid:pk>/', DepartmentDetailView.as_view(), name='department_detail'),
    path('departments/<uuid:pk>/edit/', DepartmentUpdateView.as_view(), name='department_edit'),
    path('departments/<uuid:pk>/toggle-active/', DepartmentToggleActiveView.as_view(), name='department_toggle_active'),
    path('departments/<uuid:pk>/assign-head/', DepartmentAssignHeadView.as_view(), name='department_assign_head'),
    # Positions
    path('positions/', PositionListView.as_view(), name='position_list'),
    path('positions/create/', PositionCreateView.as_view(), name='position_create'),
    path('positions/<uuid:pk>/edit/', PositionUpdateView.as_view(), name='position_edit'),
    path('positions/<uuid:pk>/toggle-active/', PositionToggleActiveView.as_view(), name='position_toggle_active'),
    # Vice Rector Responsibilities
    path('vice-rectors/responsibilities/', ViceRectorResponsibilityListView.as_view(), name='responsibility_list'),
    path('vice-rectors/responsibilities/create/', ViceRectorResponsibilityCreateView.as_view(), name='responsibility_create'),
    path('vice-rectors/responsibilities/<uuid:pk>/delete/', ViceRectorResponsibilityDeleteView.as_view(), name='responsibility_delete'),
]
