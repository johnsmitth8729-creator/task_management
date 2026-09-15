import datetime
from django.db.models import Avg, Count, Q
from django.utils import timezone

from accounts.models import Role
from automation.models import AutomationRule, SLAPolicy
from kpi.models import KPIPeriod
from operations.models import UniversityRequest
from organization.models import Department
from tasks.models import Task, TaskAssignment, TaskSubmission


class RoleContextBuilder:
    """
    Builds authorization-strictly bounded contextual data payloads for AI grounding.
    Enforces Universal RBAC and Strict Salary Privacy at the query construction layer.
    """

    @classmethod
    def build_context(cls, user) -> dict:
        now = timezone.now()
        today = now.date()

        context = {
            'user_role': cls._get_primary_role_display(user),
            'timestamp': now.isoformat(),
            'accessible_departments': [],
            'metrics': {},
            'tasks_summary': {},
            'urgent_alerts': [],
        }

        # 1. Technical Superadmin & University Rector
        if user.is_superuser or user.is_rector:
            context['scope'] = 'UNIVERSITY_WIDE'
            total_tasks = Task.objects.count()
            open_tasks = Task.objects.filter(status__in=[Task.Status.CREATED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS]).count()
            completed_tasks = Task.objects.filter(status=Task.Status.COMPLETED).count()
            overdue_tasks = Task.objects.filter(
                status__in=[Task.Status.CREATED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS],
                deadline__lt=today
            ).count()

            context['metrics'] = {
                'total_tasks': total_tasks,
                'open_tasks': open_tasks,
                'completed_tasks': completed_tasks,
                'overdue_tasks': overdue_tasks,
                'total_departments': Department.objects.filter(is_active=True).count(),
                'pending_requests': UniversityRequest.objects.filter(status__in=[UniversityRequest.Status.SUBMITTED, UniversityRequest.Status.IN_REVIEW]).count(),
            }

            # Top bottlenecks: departments with highest overdue tasks
            dept_overdue = Department.objects.filter(
                tasks__status__in=[Task.Status.CREATED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS],
                tasks__deadline__lt=today
            ).annotate(overdue_count=Count('tasks')).order_by('-overdue_count')[:5]

            context['bottlenecks'] = [
                {'department': d.name, 'overdue_count': d.overdue_count} for d in dept_overdue
            ]

        # 2. Supervising Vice Rector
        elif user.is_vice_rector:
            context['scope'] = 'VICE_RECTOR_SECTOR'
            depts = Department.objects.filter(
                vice_rector_responsibilities__vice_rector=user,
                vice_rector_responsibilities__is_active=True
            ).distinct()
            dept_ids = [d.id for d in depts]
            context['accessible_departments'] = [d.name for d in depts]

            sector_tasks = Task.objects.filter(responsible_department_id__in=dept_ids)
            context['metrics'] = {
                'sector_total_tasks': sector_tasks.count(),
                'sector_open_tasks': sector_tasks.filter(status__in=[Task.Status.CREATED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS]).count(),
                'sector_overdue_tasks': sector_tasks.filter(
                    status__in=[Task.Status.CREATED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS],
                    deadline__lt=today
                ).count(),
                'pending_stage2_approvals': TaskSubmission.objects.filter(
                    status=TaskSubmission.SubmissionStatus.FIRST_APPROVED,
                    assignment__task__responsible_department_id__in=dept_ids
                ).count(),
            }

        # 3. Department Head
        elif user.is_department_head and user.department:
            dept = user.department
            context['scope'] = 'DEPARTMENT'
            context['accessible_departments'] = [dept.name]
            dept_tasks = Task.objects.filter(responsible_department=dept)

            context['metrics'] = {
                'department_name': dept.name,
                'dept_total_tasks': dept_tasks.count(),
                'dept_open_tasks': dept_tasks.filter(status__in=[Task.Status.CREATED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS]).count(),
                'dept_overdue_tasks': dept_tasks.filter(
                    status__in=[Task.Status.CREATED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS],
                    deadline__lt=today
                ).count(),
                'pending_first_approvals': TaskSubmission.objects.filter(
                    status=TaskSubmission.SubmissionStatus.PENDING_FIRST_APPROVAL,
                    assignment__task__responsible_department=dept
                ).count(),
            }

        # 4. Standard Employee / Academic Staff
        else:
            context['scope'] = 'PERSONAL'
            my_assignments = TaskAssignment.objects.filter(user=user).select_related('task')
            my_tasks = [a.task for a in my_assignments]
            my_open_assignments = my_assignments.filter(
                assignment_status__in=[TaskAssignment.AssignmentStatus.ASSIGNED, TaskAssignment.AssignmentStatus.IN_PROGRESS]
            )

            context['metrics'] = {
                'my_total_assignments': my_assignments.count(),
                'my_active_tasks': my_open_assignments.count(),
                'my_overdue_tasks': my_open_assignments.filter(task__deadline__lt=today).count(),
                'my_submitted_awaiting_approval': my_assignments.filter(assignment_status=TaskAssignment.AssignmentStatus.SUBMITTED).count(),
            }

        return context

    @classmethod
    def _get_primary_role_display(cls, user) -> str:
        if user.is_superuser:
            return "Technical Superadmin"
        if user.is_rector:
            return "University Rector"
        if user.is_vice_rector:
            return "Vice Rector"
        if user.is_department_head:
            return "Department Head"
        if user.is_hr:
            return "HR Manager"
        if user.is_finance:
            return "Finance Director"
        return "University Staff / Employee"
