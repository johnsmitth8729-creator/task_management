"""
core/navigation.py

Centralized enterprise navigation registry for University Task Management Platform.
Implements one unified navigation architecture across all roles:
- Single source of truth for menu items, icons, URLs, permissions, badges, and active states.
- Role-based visibility and scope-based authorization.
- Zero duplicate items.
- Automatically suppresses empty groups.
- Responsive, accessible, and translation-ready.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext_lazy as _


@dataclass
class NavigationItem:
    """Represents an individual navigation link."""
    id: str
    label: Any
    url_name: str
    icon: str
    url_kwargs: Optional[Any] = None
    url_params: Optional[str] = None
    active_patterns: List[str] = field(default_factory=list)
    badge_callback: Optional[Callable[[Any], Optional[dict]]] = None
    visibility_callback: Optional[Callable[[Any], bool]] = None
    title: Optional[Any] = None

    def get_url(self, request=None) -> str:
        """Resolve the target URL safely."""
        try:
            kwargs = self.url_kwargs or {}
            if callable(kwargs):
                kwargs = kwargs(request)
            url = reverse(self.url_name, kwargs=kwargs)
            if self.url_params:
                url += self.url_params
            return url
        except NoReverseMatch:
            return '#'

    def is_visible(self, request) -> bool:
        """Evaluate visibility callback against request and user."""
        if not request.user.is_authenticated:
            return False
        if self.visibility_callback is not None:
            try:
                return bool(self.visibility_callback(request))
            except Exception:
                return False
        return True

    def is_active(self, request) -> bool:
        """Determine if this item matches the current page."""
        if not hasattr(request, 'resolver_match') or not request.resolver_match:
            return False

        rm = request.resolver_match
        current_url_name = rm.url_name or ''
        current_view_name = rm.view_name or ''
        current_namespace = rm.namespace or ''
        current_path = request.path or ''

        # Check explicit active patterns
        for pattern in self.active_patterns:
            if ':' in pattern:
                if pattern in current_view_name:
                    return True
            else:
                if not current_namespace and pattern in current_url_name:
                    return True

        # Check exact view match:
        # If self.url_name has a namespace (contains ':'), compare directly with current_view_name.
        # If self.url_name has no namespace, it only matches when the current route is ALSO unnamespaced!
        if ':' in self.url_name:
            view_matches = (current_view_name == self.url_name)
        else:
            view_matches = (not current_namespace and (current_url_name == self.url_name or current_view_name == self.url_name))

        # Check parameter-aware matching if item specifies url_params
        if self.url_params and view_matches:
            from urllib.parse import parse_qs
            param_dict = parse_qs(self.url_params.lstrip('?'))
            match = True
            for k, vals in param_dict.items():
                if request.GET.get(k) not in vals:
                    match = False
                    break
            if match:
                return True
            return False

        # If this item has NO url_params, but another item uses the same url_name with params,
        # ensure we don't highlight the generic item when special params are present
        if not self.url_params and view_matches:
            if self.url_name == 'task_list':
                if request.GET.get('scope') or request.GET.get('is_overdue'):
                    return False
            return True

        # Check exact path match (fallback)
        target_url = self.get_url(request)
        if target_url and target_url != '#':
            base_target = target_url.split('?')[0].rstrip('/')
            if base_target and base_target not in ['/en', '/uz', '']:
                if current_path.rstrip('/') == base_target:
                    return True

        return False

    def get_badge(self, request) -> Optional[dict]:
        """Compute badge payload: {'count': int, 'css_class': str}."""
        if self.badge_callback is not None:
            try:
                return self.badge_callback(request)
            except Exception:
                return None
        return None


@dataclass
class NavigationGroup:
    """Represents a top-level section containing items."""
    id: str
    label: Any
    icon: str
    items: List[NavigationItem]
    visibility_callback: Optional[Callable[[Any], bool]] = None
    landing_item_id: Optional[str] = None
    active_patterns: List[str] = field(default_factory=list)
    badge_callback: Optional[Callable[[Any], Optional[dict]]] = None

    def get_visible_items(self, request) -> List[NavigationItem]:
        """Return only items visible to current user."""
        return [item for item in self.items if item.is_visible(request)]

    def is_visible(self, request) -> bool:
        """Group is visible only if its callback passes AND it has at least one visible item."""
        if not request.user.is_authenticated:
            return False
        if self.visibility_callback is not None:
            try:
                if not bool(self.visibility_callback(request)):
                    return False
            except Exception:
                return False
        return len(self.get_visible_items(request)) > 0

    def has_active_child(self, request) -> bool:
        """Check if any visible child is active."""
        for item in self.get_visible_items(request):
            if item.is_active(request):
                return True
        return False

    def is_active(self, request) -> bool:
        """Determine if this section is currently active."""
        if self.has_active_child(request):
            return True
        if not hasattr(request, 'resolver_match') or not request.resolver_match:
            return False
        rm = request.resolver_match
        current_url_name = rm.url_name or ''
        current_view_name = rm.view_name or ''
        current_namespace = rm.namespace or ''
        for pattern in self.active_patterns:
            if ':' in pattern:
                if pattern in current_view_name:
                    return True
            else:
                if pattern == current_namespace or (not current_namespace and pattern in current_url_name):
                    return True
        return False

    def get_landing_url(self, request) -> str:
        """Resolve the primary landing URL for this section."""
        visible = self.get_visible_items(request)
        if not visible:
            return '#'
        if self.landing_item_id:
            for item in visible:
                if item.id == self.landing_item_id:
                    return item.get_url(request)
        return visible[0].get_url(request)

    def get_badge(self, request) -> Optional[dict]:
        """Compute section-level badge payload."""
        if self.badge_callback is not None:
            try:
                return self.badge_callback(request)
            except Exception:
                return None
        total_count = 0
        css_class = 'bg-primary'
        for item in self.get_visible_items(request):
            b = item.get_badge(request)
            if b and isinstance(b, dict) and b.get('count'):
                total_count += b['count']
                if 'danger' in b.get('css_class', ''):
                    css_class = 'bg-danger'
                elif css_class != 'bg-danger' and 'warning' in b.get('css_class', ''):
                    css_class = 'bg-warning text-dark'
        if total_count > 0:
            return {'count': total_count, 'css_class': css_class}
        return None


# ============================================================================
# BADGE CALLBACKS (Lightweight, reuse existing context or cached properties)
# ============================================================================

def _notifications_badge(request):
    unread = getattr(request, '_unread_notifications_count', None)
    if unread is None:
        from core.models import Notification
        unread = Notification.objects.filter(recipient=request.user, is_read=False).count()
        setattr(request, '_unread_notifications_count', unread)
    if unread > 0:
        return {'count': unread, 'css_class': 'bg-danger'}
    return None


def _employee_incoming_badge(request):
    user = request.user
    if not user.is_authenticated or user.is_rector:
        return None
    from tasks.models import TaskAssignment, Task
    qs = TaskAssignment.objects.filter(
        user=user,
        assignment_status=TaskAssignment.AssignmentStatus.ASSIGNED
    ).exclude(task__status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED])

    active_year = getattr(request, 'active_year', None) or (request.session.get('active_year') if hasattr(request, 'session') else None)
    if active_year:
        try:
            qs = qs.filter(task__created_at__year=int(active_year))
        except (ValueError, TypeError):
            pass

    seen_ids = request.session.get('seen_incoming_tasks', []) if hasattr(request, 'session') else []
    if seen_ids:
        qs = qs.exclude(id__in=seen_ids)

    count = qs.count()
    if count > 0:
        return {'count': count, 'css_class': 'bg-primary'}
    return None


def _tasks_under_control_badge(request):
    user = request.user
    if not user.is_authenticated:
        return None
    from django.db.models import Q
    from tasks.models import Task

    qs = Task.objects.exclude(status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED])
    if user.is_superuser or user.is_rector:
        qs = qs.filter(Q(creator=user) | Q(status__in=[Task.Status.ASSIGNED, Task.Status.IN_PROGRESS]))
    elif user.is_vice_rector:
        scoped = user.get_scoped_departments()
        qs = qs.filter(Q(creator=user) | Q(responsible_department__in=scoped))
    elif user.is_department_head and user.department:
        qs = qs.filter(Q(creator=user) | Q(responsible_department=user.department))
    else:
        qs = qs.filter(creator=user)

    active_year = getattr(request, 'active_year', None) or (request.session.get('active_year') if hasattr(request, 'session') else None)
    if active_year:
        try:
            qs = qs.filter(created_at__year=int(active_year))
        except (ValueError, TypeError):
            pass

    seen_ids = request.session.get('seen_control_tasks', []) if hasattr(request, 'session') else []
    if seen_ids:
        qs = qs.exclude(id__in=seen_ids)

    count = qs.count()
    if count > 0:
        return {'count': count, 'css_class': 'bg-info text-dark'}
    return None


def _overdue_tasks_badge(request):
    user = request.user
    if not user.is_authenticated:
        return None
    from django.utils import timezone
    from django.db.models import Q
    from tasks.models import Task

    now = timezone.now().date()
    qs = Task.objects.filter(
        deadline__lt=now
    ).exclude(status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED])

    if user.is_superuser or user.is_rector:
        qs = qs.filter(Q(creator=user) | Q(status__in=[Task.Status.ASSIGNED, Task.Status.IN_PROGRESS]))
    elif user.is_vice_rector:
        scoped = user.get_scoped_departments()
        qs = qs.filter(Q(creator=user) | Q(responsible_department__in=scoped))
    elif user.is_department_head and user.department:
        qs = qs.filter(Q(creator=user) | Q(responsible_department=user.department))
    else:
        qs = qs.filter(Q(assignments__user=user) | Q(creator=user)).distinct()

    active_year = getattr(request, 'active_year', None) or (request.session.get('active_year') if hasattr(request, 'session') else None)
    if active_year:
        try:
            qs = qs.filter(created_at__year=int(active_year))
        except (ValueError, TypeError):
            pass

    seen_ids = request.session.get('seen_overdue_tasks', []) if hasattr(request, 'session') else []
    if seen_ids:
        qs = qs.exclude(id__in=seen_ids)

    count = qs.count()
    if count > 0:
        return {'count': count, 'css_class': 'bg-danger'}
    return None


def _dept_first_approval_badge(request):
    user = request.user
    if not user.is_authenticated:
        return None
    if user.is_department_head and user.department:
        from tasks.models import TaskSubmission, Task
        qs = TaskSubmission.objects.filter(
            status=TaskSubmission.SubmissionStatus.PENDING_FIRST_APPROVAL
        ).exclude(
            task__status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED]
        )
        if user.department and not user.is_rector:
            qs = qs.filter(task__responsible_department=user.department)
        elif user.is_vice_rector:
            scoped_depts = user.get_scoped_departments()
            qs = qs.filter(task__responsible_department__in=scoped_depts)

        active_year = getattr(request, 'active_year', None) or (request.session.get('active_year') if hasattr(request, 'session') else None)
        if active_year:
            try:
                qs = qs.filter(task__created_at__year=int(active_year))
            except (ValueError, TypeError):
                pass

        seen_ids = request.session.get('seen_first_approvals', []) if hasattr(request, 'session') else []
        if seen_ids:
            qs = qs.exclude(id__in=seen_ids)

        count = qs.count()
        if count > 0:
            return {'count': count, 'css_class': 'bg-warning text-dark'}
    return None


def _final_approval_badge(request):
    user = request.user
    if not user.is_authenticated:
        return None
    if user.is_superuser or user.is_rector or user.is_vice_rector:
        from django.db.models import Q
        from tasks.models import TaskAssignment, Task
        qs = TaskAssignment.objects.exclude(
            task__status__in=[Task.Status.CANCELLED, Task.Status.ARCHIVED]
        ).filter(
            Q(assignment_status__in=[
                TaskAssignment.AssignmentStatus.SECOND_APPROVAL,
                TaskAssignment.AssignmentStatus.SUBMITTED,
            ])
            | Q(task__status=Task.Status.COMPLETED)
        ).exclude(task__signatures__status='SIGNED')

        if user.is_vice_rector and not (user.is_rector or user.is_superuser):
            scoped_depts = user.get_scoped_departments()
            qs = qs.filter(task__responsible_department__in=scoped_depts)

        active_year = getattr(request, 'active_year', None) or (request.session.get('active_year') if hasattr(request, 'session') else None)
        if active_year:
            try:
                qs = qs.filter(task__created_at__year=int(active_year))
            except (ValueError, TypeError):
                pass

        seen_ids = request.session.get('seen_second_approvals', []) if hasattr(request, 'session') else []
        if seen_ids:
            qs = qs.exclude(Q(id__in=seen_ids) | Q(task_id__in=seen_ids))

        count = qs.values('task_id').distinct().count()
        if count > 0:
            return {'count': count, 'css_class': 'bg-primary'}
    return None


def _approvals_hub_badge(request):
    user = request.user
    if not user.is_authenticated:
        return None

    if user.is_superuser or user.is_rector or user.is_vice_rector:
        return _final_approval_badge(request)
    elif user.is_department_head and user.department:
        return _dept_first_approval_badge(request)
    else:
        from tasks.models import TaskAssignment, Task
        qs = TaskAssignment.objects.filter(
            user=user,
            assignment_status=TaskAssignment.AssignmentStatus.SUBMITTED
        ).exclude(
            task__status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED]
        )
        active_year = getattr(request, 'active_year', None) or (request.session.get('active_year') if hasattr(request, 'session') else None)
        if active_year:
            try:
                qs = qs.filter(task__created_at__year=int(active_year))
            except (ValueError, TypeError):
                pass
        seen_ids = request.session.get('seen_submitted_approvals', []) if hasattr(request, 'session') else []
        if seen_ids:
            qs = qs.exclude(id__in=seen_ids)
        count = qs.count()
        if count > 0:
            return {'count': count, 'css_class': 'bg-purple text-white'}
    return None


# ============================================================================
# NAVIGATION REGISTRY BUILDER
# ============================================================================

def build_navigation_registry() -> List[NavigationGroup]:
    """
    Builds the master list of conceptual enterprise navigation groups.
    Visibility callbacks determine runtime role and scope evaluation.
    """
    return [
        # --------------------------------------------------------------------
        # 1. MAIN / DASHBOARD (Single-item top-level link)
        # --------------------------------------------------------------------
        NavigationGroup(
            id='main',
            label=_('Main'),
            icon='bi bi-speedometer2',
            landing_item_id='dashboard',
            active_patterns=[],
            items=[
                NavigationItem(
                    id='dashboard',
                    label=_('Dashboard'),
                    url_name='dashboard',
                    icon='bi bi-speedometer2',
                    title=_('Dashboard Overview'),
                ),
            ],
        ),

        # --------------------------------------------------------------------
        # 2. TASKS & EXECUTION (Topshiriqlar va ijro - Unified edo.ijro.uz style)
        # --------------------------------------------------------------------
        NavigationGroup(
            id='tasks',
            label=_('Tasks & Execution'),
            icon='bi bi-check2-square',
            landing_item_id='task_list',
            active_patterns=['task', 'workflow', 'assignment', 'submission', 'dept_task'],
            items=[
                # All Tasks (scoped to user's organizational boundary)
                NavigationItem(
                    id='task_list',
                    label=_('All Tasks'),
                    url_name='task_list',
                    icon='bi bi-list-task',
                    title=_('All Scoped Tasks'),
                    active_patterns=['task_detail', 'task_edit', 'task_history'],
                ),
                # Incoming assignments to accept
                NavigationItem(
                    id='employee_incoming',
                    label=_('Incoming'),
                    url_name='employee_incoming',
                    icon='bi bi-inbox-fill text-primary',
                    title=_('New Incoming Assignments'),
                    badge_callback=_employee_incoming_badge,
                    active_patterns=['assignment_accept'],
                    visibility_callback=lambda r: not r.user.is_rector,
                ),
                # Active assignments in progress
                NavigationItem(
                    id='employee_inprogress',
                    label=_('In Progress'),
                    url_name='employee_inprogress',
                    icon='bi bi-play-circle-fill text-warning',
                    title=_('Assignments In Progress'),
                    active_patterns=['assignment_detail', 'assignment_progress', 'assignment_add_note', 'assignment_submit'],
                    visibility_callback=lambda r: not r.user.is_rector,
                ),
                # Under Control (Supervision and monitoring)
                NavigationItem(
                    id='tasks_under_control',
                    label=_('Under Control'),
                    url_name='task_list',
                    url_params='?scope=control',
                    icon='bi bi-eye-fill text-info',
                    title=_('Tasks Under Supervision & Control'),
                    badge_callback=_tasks_under_control_badge,
                ),
                # Dynamic Approvals Hub
                NavigationItem(
                    id='approvals_hub',
                    label=_('In Approval'),
                    url_name='workflow_approvals_hub',
                    icon='bi bi-shield-check text-purple',
                    title=_('Approval Center & Submission Review'),
                    badge_callback=_approvals_hub_badge,
                    active_patterns=[
                        'workflow_approvals_hub',
                        'dept_first_approval',
                        'management_second_approval',
                        'employee_first_approval',
                        'employee_second_approval',
                        'submission_detail',
                        'dept_approve_submission',
                        'dept_reject_submission',
                        'management_second_approval_detail',
                        'management_final_approve',
                        'management_reject',
                    ],
                ),
                # Successfully Completed Tasks Archive
                NavigationItem(
                    id='completed_tasks',
                    label=_('Completed Tasks'),
                    url_name='completed_tasks',
                    icon='bi bi-patch-check-fill text-success',
                    title=_('Successfully Completed Archive'),
                ),
                # Rejected / Returned Tasks Archive
                NavigationItem(
                    id='rejected_tasks',
                    label=_('Rejected Tasks'),
                    url_name='rejected_tasks',
                    icon='bi bi-x-octagon-fill text-danger',
                    title=_('Rejected & Returned Tasks'),
                ),
                # Overdue Tasks
                NavigationItem(
                    id='overdue_tasks',
                    label=_('Overdue'),
                    url_name='task_list',
                    url_params='?is_overdue=1',
                    icon='bi bi-exclamation-triangle-fill text-danger',
                    title=_('Overdue Tasks Requiring Action'),
                    badge_callback=_overdue_tasks_badge,
                ),
                # Department Head Task Distribution
                NavigationItem(
                    id='dept_task_list',
                    label=_('Task Distribution'),
                    url_name='dept_task_list',
                    icon='bi bi-kanban text-primary',
                    active_patterns=['dept_task_list', 'dept_task_detail', 'dept_assign_employees'],
                    visibility_callback=lambda r: (
                        r.user.is_department_head and not r.user.is_rector and not r.user.is_superuser
                    ),
                ),
                # Task Types (Superadmin and Rector only)
                NavigationItem(
                    id='task_type_list',
                    label=_('Task Types'),
                    url_name='task_type_list',
                    icon='bi bi-tags',
                    active_patterns=['task_type'],
                    visibility_callback=lambda r: r.user.is_superuser or r.user.is_rector,
                ),
            ],
        ),

        # --------------------------------------------------------------------
        # 3. DOCUMENTS & REPORTS
        # --------------------------------------------------------------------
        NavigationGroup(
            id='documents',
            label=_('Documents & Reports'),
            icon='bi bi-file-earmark-text-fill',
            landing_item_id='official_documents',
            active_patterns=['operations:document', 'analytics:report', 'analytics:signature'],
            items=[
                NavigationItem(
                    id='official_documents',
                    label=_('Official Documents'),
                    url_name='operations:document_list',
                    icon='bi bi-file-earmark-ruled text-secondary',
                    active_patterns=['operations:document'],
                ),
                NavigationItem(
                    id='report_center',
                    label=_('Report Center'),
                    url_name='analytics:report_center',
                    icon='bi bi-file-earmark-bar-graph text-info',
                    active_patterns=['analytics:report'],
                    visibility_callback=lambda r: (
                        r.user.is_superuser or r.user.is_rector or r.user.is_vice_rector or
                        r.user.is_department_head or r.user.is_hr or r.user.is_finance
                    ),
                ),
                NavigationItem(
                    id='signature_analytics',
                    label=_('Digital Signatures'),
                    url_name='analytics:signature_analytics',
                    icon='bi bi-shield-check text-success',
                    visibility_callback=lambda r: (
                        r.user.is_superuser or r.user.is_rector or
                        r.user.is_vice_rector or r.user.is_department_head
                    ),
                ),
            ],
        ),

        # --------------------------------------------------------------------
        # 4. PERFORMANCE & KPI
        # --------------------------------------------------------------------
        NavigationGroup(
            id='performance',
            label=_('Performance & KPI'),
            icon='bi bi-graph-up-arrow',
            landing_item_id='kpi_dashboard',
            active_patterns=['kpi', 'analytics:index', 'analytics:executive', 'analytics:department', 'analytics:personal'],
            items=[
                NavigationItem(
                    id='kpi_dashboard',
                    label=_('Performance Dashboard'),
                    url_name='kpi:dashboard',
                    icon='bi bi-speedometer text-info',
                    active_patterns=['kpi:dashboard'],
                ),
                NavigationItem(
                    id='kpi_assignment_list',
                    label=_('KPI Evaluations'),
                    url_name='kpi:assignment_list',
                    icon='bi bi-list-check',
                    active_patterns=['kpi:assignment', 'kpi:evaluate'],
                    visibility_callback=lambda r: (
                        r.user.is_superuser or r.user.is_rector or
                        getattr(r.user, 'can_manage_kpi', False)
                    ),
                ),
                NavigationItem(
                    id='kpi_definition_list',
                    label=_('KPI Catalog'),
                    url_name='kpi:definition_list',
                    icon='bi bi-sliders',
                    active_patterns=['kpi:definition'],
                    visibility_callback=lambda r: (
                        r.user.is_superuser or r.user.is_rector or
                        getattr(r.user, 'can_manage_kpi', False)
                    ),
                ),
                NavigationItem(
                    id='analytics_overview',
                    label=_('Institutional Analytics'),
                    url_name='analytics:executive_dashboard',
                    icon='bi bi-pie-chart-fill text-primary',
                    active_patterns=['analytics:executive', 'analytics:department', 'analytics:personal'],
                ),
            ],
        ),

        # --------------------------------------------------------------------
        # 5. ORGANIZATION & STRUCTURE
        # --------------------------------------------------------------------
        NavigationGroup(
            id='organization',
            label=_('Organization'),
            icon='bi bi-building-fill',
            active_patterns=['organization', 'department', 'position', 'responsibility', 'user_list'],
            visibility_callback=lambda r: (
                r.user.is_superuser or r.user.is_rector or
                r.user.is_vice_rector or r.user.is_department_head
            ),
            items=[
                # Dept Head: My Department
                NavigationItem(
                    id='my_department_detail',
                    label=_('My Department'),
                    url_name='department_detail',
                    icon='bi bi-building',
                    url_kwargs=lambda r: {'pk': r.user.department.pk} if r.user.department else {},
                    visibility_callback=lambda r: (
                        r.user.is_department_head and not r.user.is_rector and
                        not r.user.is_vice_rector and not r.user.is_superuser and
                        r.user.department is not None
                    ),
                ),
                # Vice Rector: My Responsible Departments
                NavigationItem(
                    id='vr_departments',
                    label=_('My Departments'),
                    url_name='department_list',
                    icon='bi bi-building',
                    visibility_callback=lambda r: (
                        r.user.is_vice_rector and not r.user.is_rector and not r.user.is_superuser
                    ),
                ),
                # Superadmin & Rector: University Structure Tree
                NavigationItem(
                    id='org_structure',
                    label=_('University Structure'),
                    url_name='organization_overview',
                    icon='bi bi-diagram-3',
                    visibility_callback=lambda r: r.user.is_superuser or r.user.is_rector,
                ),
                # Superadmin & Rector: Departments CRUD
                NavigationItem(
                    id='departments_list',
                    label=_('Departments'),
                    url_name='department_list',
                    icon='bi bi-building',
                    visibility_callback=lambda r: r.user.is_superuser or r.user.is_rector,
                ),
                # Superadmin & Rector: Positions CRUD
                NavigationItem(
                    id='positions_list',
                    label=_('Positions'),
                    url_name='position_list',
                    icon='bi bi-briefcase',
                    visibility_callback=lambda r: r.user.is_superuser or r.user.is_rector,
                ),
                # Superadmin & Rector: VR Responsibilities
                NavigationItem(
                    id='vr_responsibilities',
                    label=_('Vice Rectors'),
                    url_name='responsibility_list',
                    icon='bi bi-diagram-2',
                    visibility_callback=lambda r: r.user.is_superuser or r.user.is_rector,
                ),
                # Staff & Employees List
                NavigationItem(
                    id='staff_list',
                    label=_('Employees'),
                    url_name='user_list',
                    icon='bi bi-people',
                    visibility_callback=lambda r: (
                        r.user.is_superuser or r.user.is_rector or
                        r.user.is_vice_rector or r.user.is_department_head
                    ),
                ),
            ],
        ),

        # --------------------------------------------------------------------
        # 6. PEOPLE & HR (HR Team, Rector, Superadmin)
        # --------------------------------------------------------------------
        NavigationGroup(
            id='hr',
            label=_('People & HR'),
            icon='bi bi-people-fill',
            landing_item_id='hr_overview',
            active_patterns=['hr:'],
            visibility_callback=lambda r: r.user.is_hr or r.user.is_rector or r.user.is_superuser,
            items=[
                NavigationItem(
                    id='hr_overview',
                    label=_('Employee Directory'),
                    url_name='hr:overview',
                    icon='bi bi-people-fill',
                    active_patterns=['hr:overview', 'hr:employee'],
                ),
                NavigationItem(
                    id='hr_grades',
                    label=_('Employee Grades'),
                    url_name='hr:grade_list',
                    icon='bi bi-award',
                    active_patterns=['hr:grade'],
                ),
                NavigationItem(
                    id='hr_permissions',
                    label=_('HR Permissions'),
                    url_name='hr:permissions_config',
                    icon='bi bi-shield-lock',
                    active_patterns=['hr:permissions'],
                    visibility_callback=lambda r: r.user.is_superuser or r.user.is_rector,
                ),
            ],
        ),

        # --------------------------------------------------------------------
        # 7. PAYROLL & COMPENSATION (Role Scoped: Finance / Superadmin / Self)
        # --------------------------------------------------------------------
        NavigationGroup(
            id='payroll',
            label=_('Payroll & Compensation'),
            icon='bi bi-cash-stack',
            landing_item_id='payroll_dashboard',
            active_patterns=['payroll'],
            items=[
                # Operational Dashboard for Finance & Superadmin
                NavigationItem(
                    id='payroll_dashboard',
                    label=_('Payroll Dashboard'),
                    url_name='payroll:dashboard',
                    icon='bi bi-speedometer2 text-primary',
                    visibility_callback=lambda r: (
                        r.user.is_superuser or r.user.is_finance or r.user.is_rector or
                        r.user.is_vice_rector or r.user.is_department_head
                    ),
                ),
                # Finance / Admin Operational Items
                NavigationItem(
                    id='payroll_periods',
                    label=_('Payroll Periods'),
                    url_name='payroll:period_list',
                    icon='bi bi-calendar3',
                    visibility_callback=lambda r: r.user.is_superuser or r.user.is_finance,
                ),
                NavigationItem(
                    id='payroll_records',
                    label=_('Payroll Records'),
                    url_name='payroll:record_list',
                    icon='bi bi-receipt',
                    visibility_callback=lambda r: (
                        r.user.is_superuser or r.user.is_finance or r.user.is_rector
                    ),
                ),
                NavigationItem(
                    id='payroll_salaries',
                    label=_('Salary Management'),
                    url_name='payroll:employee_list',
                    icon='bi bi-wallet2',
                    visibility_callback=lambda r: (
                        r.user.is_superuser or
                        (r.user.is_finance and getattr(r, '_can_manage_salary', True))
                    ),
                ),
                NavigationItem(
                    id='payroll_rules',
                    label=_('Compensation Rules'),
                    url_name='payroll:component_list',
                    icon='bi bi-sliders',
                    visibility_callback=lambda r: r.user.is_superuser or r.user.is_finance,
                ),
                NavigationItem(
                    id='payroll_reports',
                    label=_('Payroll Reports'),
                    url_name='payroll:reports_summary',
                    icon='bi bi-file-earmark-bar-graph',
                    visibility_callback=lambda r: (
                        r.user.is_superuser or r.user.is_finance or
                        r.user.is_rector or r.user.is_vice_rector
                    ),
                ),
                # Personal Salary & Payslips for every user
                NavigationItem(
                    id='my_salary',
                    label=_('My Salary'),
                    url_name='payroll:my_salary',
                    icon='bi bi-person-lines-fill text-success',
                ),
                NavigationItem(
                    id='my_payslips',
                    label=_('My Payslips'),
                    url_name='payroll:my_payslips',
                    icon='bi bi-file-earmark-text',
                ),
            ],
        ),

        # --------------------------------------------------------------------
        # 8. COMMUNICATION & INTEGRATIONS
        # --------------------------------------------------------------------
        NavigationGroup(
            id='communication',
            label=_('Communication'),
            icon='bi bi-chat-left-text-fill',
            landing_item_id='notifications',
            active_patterns=['notifications', 'communication'],
            items=[
                NavigationItem(
                    id='notifications',
                    label=_('Notifications'),
                    url_name='notifications',
                    icon='bi bi-bell-fill text-warning',
                    badge_callback=_notifications_badge,
                ),
                NavigationItem(
                    id='telegram_connect',
                    label=_('Telegram Bot'),
                    url_name='communication:telegram_connect',
                    icon='bi bi-telegram text-primary',
                ),
                NavigationItem(
                    id='calendar_settings',
                    label=_('Calendar Feed'),
                    url_name='communication:calendar_settings',
                    icon='bi bi-calendar3',
                ),
                NavigationItem(
                    id='integration_hub',
                    label=_('Integration Hub'),
                    url_name='communication:integration_hub',
                    icon='bi bi-plug-fill',
                    visibility_callback=lambda r: r.user.is_superuser,
                ),
            ],
        ),

        # --------------------------------------------------------------------
        # 9. OPERATIONS & CAMPUS SERVICES
        # --------------------------------------------------------------------
        NavigationGroup(
            id='operations',
            label=_('Operations & Services'),
            icon='bi bi-gear-wide-connected',
            landing_item_id='service_catalog',
            active_patterns=['operations:service', 'operations:request', 'operations:my_requests', 'operations:approval_queue'],
            items=[
                NavigationItem(
                    id='service_catalog',
                    label=_('Service Catalog'),
                    url_name='operations:service_catalog',
                    icon='bi bi-grid-3x3-gap-fill text-primary',
                ),
                NavigationItem(
                    id='my_applications',
                    label=_('My Applications'),
                    url_name='operations:my_requests',
                    icon='bi bi-person-lines-fill text-info',
                ),
                NavigationItem(
                    id='requests_approval',
                    label=_('Requests Approval'),
                    url_name='operations:approval_queue',
                    icon='bi bi-check2-circle text-success',
                    visibility_callback=lambda r: (
                        r.user.is_department_head or r.user.is_vice_rector or
                        r.user.is_rector or r.user.is_superuser or
                        r.user.is_hr or r.user.is_finance
                    ),
                ),
            ],
        ),

        # --------------------------------------------------------------------
        # 10. AUTOMATION & SLA (Leadership & Superadmin)
        # --------------------------------------------------------------------
        NavigationGroup(
            id='automation',
            label=_('Automation & SLA'),
            icon='bi bi-lightning-charge-fill',
            landing_item_id='automation_hub',
            active_patterns=['automation'],
            visibility_callback=lambda r: (
                r.user.is_superuser or r.user.is_rector or r.user.is_vice_rector
            ),
            items=[
                NavigationItem(
                    id='automation_hub',
                    label=_('Automation Hub'),
                    url_name='automation:dashboard',
                    icon='bi bi-cpu text-primary',
                ),
                NavigationItem(
                    id='automation_rules',
                    label=_('Event Rules'),
                    url_name='automation:rule_list',
                    icon='bi bi-gear-wide-connected text-info',
                ),
                NavigationItem(
                    id='recurring_tasks',
                    label=_('Recurring Tasks'),
                    url_name='automation:recurring_list',
                    icon='bi bi-arrow-repeat text-success',
                ),
                NavigationItem(
                    id='sla_policies',
                    label=_('SLA Policies'),
                    url_name='automation:sla_list',
                    icon='bi bi-clock-history text-warning',
                ),
                NavigationItem(
                    id='escalations',
                    label=_('Escalations'),
                    url_name='automation:escalation_list',
                    icon='bi bi-shield-exclamation text-danger',
                ),
                NavigationItem(
                    id='execution_logs',
                    label=_('Execution Logs'),
                    url_name='automation:execution_history',
                    icon='bi bi-journal-code',
                ),
            ],
        ),

        # --------------------------------------------------------------------
        # 11. AI & MANAGEMENT INTELLIGENCE
        # --------------------------------------------------------------------
        NavigationGroup(
            id='ai',
            label=_('AI & Intelligence'),
            icon='bi bi-robot',
            landing_item_id='ai_chat',
            active_patterns=['ai_assistant'],
            items=[
                NavigationItem(
                    id='ai_chat',
                    label=_('AI Assistant'),
                    url_name='ai_assistant:chat',
                    icon='bi bi-robot text-primary',
                ),
                NavigationItem(
                    id='ai_risks',
                    label=_('Risk Center'),
                    url_name='ai_assistant:risk_center',
                    icon='bi bi-shield-exclamation text-danger',
                    visibility_callback=lambda r: (
                        r.user.is_superuser or r.user.is_rector or
                        r.user.is_vice_rector or r.user.is_department_head
                    ),
                ),
                NavigationItem(
                    id='ai_briefings',
                    label=_('Executive Briefings'),
                    url_name='ai_assistant:briefing_list',
                    icon='bi bi-file-earmark-bar-graph text-info',
                    visibility_callback=lambda r: (
                        r.user.is_superuser or r.user.is_rector or
                        r.user.is_vice_rector or r.user.is_department_head
                    ),
                ),
            ],
        ),

        # --------------------------------------------------------------------
        # 12. SYSTEM ADMINISTRATION (Technical Superadmin Only)
        # --------------------------------------------------------------------
        NavigationGroup(
            id='admin',
            label=_('System Administration'),
            icon='bi bi-shield-lock-fill',
            landing_item_id='admin_audit',
            active_patterns=['audit', 'health', 'admin:'],
            visibility_callback=lambda r: r.user.is_superuser,
            items=[
                NavigationItem(
                    id='admin_audit',
                    label=_('Audit Logs'),
                    url_name='audit_list',
                    icon='bi bi-clock-history',
                    visibility_callback=lambda r: r.user.is_superuser,
                ),
                NavigationItem(
                    id='admin_health',
                    label=_('System Health'),
                    url_name='health_check',
                    icon='bi bi-heart-pulse text-danger',
                    visibility_callback=lambda r: r.user.is_superuser,
                ),
                NavigationItem(
                    id='admin_django',
                    label=_('Django Admin'),
                    url_name='admin:index',
                    icon='bi bi-shield-lock',
                    visibility_callback=lambda r: r.user.is_superuser,
                ),
            ],
        ),
    ]


# Cache of master registry structure
_MASTER_REGISTRY: Optional[List[NavigationGroup]] = None


def get_navigation_data(request) -> dict:
    """
    Returns the full two-level navigation data structure for the current request:
    - sections: List of serialized top-level sections for the global sidebar.
    - active_section: The active section dict (or None).
    - contextual_items: List of child items for the active section (for top bar).
    """
    global _MASTER_REGISTRY
    if _MASTER_REGISTRY is None:
        _MASTER_REGISTRY = build_navigation_registry()

    sections = []
    active_section = None
    active_has_child = False
    contextual_items = []

    for group in _MASTER_REGISTRY:
        if not group.is_visible(request):
            continue

        visible_items = group.get_visible_items(request)
        if not visible_items:
            continue

        rendered_items = []
        child_is_active = False

        for item in visible_items:
            item_active = item.is_active(request)
            if item_active:
                child_is_active = True
            rendered_items.append({
                'id': item.id,
                'label': item.label,
                'url': item.get_url(request),
                'icon': item.icon,
                'is_active': item_active,
                'badge': item.get_badge(request),
                'title': item.title or item.label,
            })

        group_active = child_is_active or group.is_active(request)
        is_single = (len(rendered_items) == 1 and group.id == 'main')
        landing_url = group.get_landing_url(request)
        badge = group.get_badge(request)

        section_dict = {
            'id': group.id,
            'label': group.label,
            'icon': group.icon,
            'is_single_item': is_single,
            'has_active_child': child_is_active,
            'is_active': False,
            'landing_url': landing_url,
            'badge': badge,
            'items': rendered_items,
        }
        sections.append(section_dict)

        if child_is_active:
            if not active_has_child:
                active_section = section_dict
                active_has_child = True
                if not is_single:
                    contextual_items = rendered_items
        elif group_active and not active_has_child:
            active_section = section_dict
            if not is_single:
                contextual_items = rendered_items

    if active_section:
        active_section['is_active'] = True

    return {
        'sections': sections,
        'active_section': active_section,
        'contextual_items': contextual_items,
    }


def get_navigation_groups(request) -> List[dict]:
    """
    Backward-compatible entry point returning the list of visible sections.
    """
    return get_navigation_data(request)['sections']

