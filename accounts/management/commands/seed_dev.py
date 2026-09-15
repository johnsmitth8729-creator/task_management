from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Role
from hr.models import EmployeeGrade, HRPermissionConfig
from kpi.models import (
    KPIAssignment,
    KPICategory,
    KPIDefinition,
    KPIPeriod,
    KPIResult,
)
from organization.models import Department, DepartmentResponsibility, Position
from organization.services import assign_department_head, assign_vice_rector_responsibility
from decimal import Decimal
from payroll.models import (
    CompensationComponent,
    KPIPayrollRule,
    PayrollAdjustment,
    PayrollLine,
    PayrollPeriod,
    PayrollPermissionConfig,
    PayrollRecord,
    PayrollTaxRule,
    SalaryBand,
    SalaryHistory,
    SalaryProfile,
)
from payroll.services import (
    approve_period_payroll,
    calculate_period_payroll,
    calculate_payroll,
    create_salary_profile,
    mark_payroll_paid,
)
from tasks.models import (
    SubTask,
    Task,
    TaskAssignment,
    TaskDependency,
    TaskTemplate,
    TaskType,
)
from tasks.services import (
    accept_assignment,
    add_dependency,
    add_task_note,
    assign_task,
    create_subtask,
    create_task,
    extend_task_deadline,
    final_approve_assignment,
    first_approve_assignment,
    first_reject_assignment,
    submit_assignment,
    update_assignment_progress,
)


class Command(BaseCommand):
    help = 'Create development-only seed data for Phase 7.'

    def handle(self, *args, **options):
        # 1. ROLES
        roles = {
            Role.Codes.RECTOR: 'Rector',
            Role.Codes.VICE_RECTOR: 'Vice Rector',
            Role.Codes.DEPARTMENT_HEAD: 'Department Head',
            Role.Codes.HR: 'HR Manager',
            Role.Codes.FINANCE: 'Finance / Accountant',
            Role.Codes.EMPLOYEE: 'Employee',
        }
        role_objects = {}
        for code, name in roles.items():
            role_objects[code], _ = Role.objects.update_or_create(
                code=code,
                defaults={'name': name, 'is_active': True},
            )

        # 1.1 EMPLOYEE GRADES
        grades_data = {
            'G1': {'name': 'Junior Specialist', 'rank': 1, 'desc': 'Entry-level professional staff'},
            'G2': {'name': 'Specialist', 'rank': 2, 'desc': 'Core professional staff'},
            'G3': {'name': 'Senior Specialist', 'rank': 3, 'desc': 'Experienced professional staff'},
            'G4': {'name': 'Lead Specialist', 'rank': 4, 'desc': 'Project and technical lead'},
            'G5': {'name': 'Principal / Department Manager', 'rank': 5, 'desc': 'Departmental manager and senior expert'},
            'G6': {'name': 'Executive Director / Dean', 'rank': 6, 'desc': 'Senior institutional executive'},
        }
        grade_objects = {}
        for code, g_info in grades_data.items():
            grade_objects[code], _ = EmployeeGrade.objects.update_or_create(
                code=code,
                defaults={
                    'name': g_info['name'],
                    'rank': g_info['rank'],
                    'description': g_info['desc'],
                    'is_active': True,
                },
            )


        # 2. DEPARTMENTS
        departments = {
            'IT': {'name': 'Information Technology', 'description': 'IT systems, infrastructure and development'},
            'LIB': {'name': 'University Library', 'description': 'Central academic library and digital resources'},
            'FIN': {'name': 'Finance & Accounting', 'description': 'Financial planning, accounting, and budgeting'},
            'HR': {'name': 'Human Resources', 'description': 'Staff management, recruitment, and personnel affairs'},
            'ACAD': {'name': 'Academic Affairs', 'description': 'Curriculum planning, student grading, and academic schedules'},
        }
        department_objects = {}
        for code, data in departments.items():
            department_objects[code], _ = Department.objects.update_or_create(
                code=code,
                defaults={
                    'name': data['name'],
                    'description': data['description'],
                    'is_active': True,
                },
            )

        # 3. POSITIONS
        positions = {
            'RECTOR': {'name': 'Rector of University', 'dept': None, 'can_supervise': True},
            'VICE_RECTOR_ACAD': {'name': 'Vice Rector for Academic Affairs', 'dept': None, 'can_supervise': True},
            'VICE_RECTOR_FIN': {'name': 'Vice Rector for Finance & Operations', 'dept': None, 'can_supervise': True},
            'DEPT_HEAD': {'name': 'Head of Department', 'dept': None, 'can_supervise': True},
            'CHIEF_LIB': {'name': 'Chief Librarian', 'dept': department_objects['LIB'], 'can_supervise': True},
            'SNR_DEV': {'name': 'Senior Software Engineer', 'dept': department_objects['IT'], 'can_supervise': False},
            'DEVELOPER': {'name': 'Software Developer', 'dept': department_objects['IT'], 'can_supervise': False},
            'LIBRARIAN': {'name': 'Librarian', 'dept': department_objects['LIB'], 'can_supervise': False},
            'SNR_ACC': {'name': 'Senior Accountant', 'dept': department_objects['FIN'], 'can_supervise': False},
            'FIN_MGR': {'name': 'Finance Manager', 'dept': department_objects['FIN'], 'can_supervise': True},
            'HR_OFFICER': {'name': 'HR Specialist', 'dept': department_objects['HR'], 'can_supervise': False},
            'ACAD_SPEC': {'name': 'Academic Coordinator', 'dept': department_objects['ACAD'], 'can_supervise': False},
        }
        position_objects = {}
        for code, data in positions.items():
            position_objects[code], _ = Position.objects.update_or_create(
                code=code,
                defaults={
                    'name': data['name'],
                    'department': data['dept'],
                    'can_supervise': data['can_supervise'],
                    'is_active': True,
                },
            )


        User = get_user_model()
        demo_password = 'ChangeMe12345!'

        # 4. USERS
        users_data = [
            # Dedicated Technical Superadmin (Django Admin Access Only)
            {
                'username': 'superadmin',
                'email': 'superadmin@example.test',
                'first_name': 'System',
                'last_name': 'Administrator',
                'role': None,
                'department': None,
                'position': None,
                'is_staff': True,
                'is_superuser': True,
            },
            # Rector (Operational University Authority — NOT Django Staff/Admin)
            {
                'username': 'rector',
                'email': 'rector@example.test',
                'first_name': 'Akbar',
                'last_name': 'Rahmatov',
                'role': Role.Codes.RECTOR,
                'department': None,
                'position': position_objects['RECTOR'],
                'is_staff': False,
                'is_superuser': False,
            },
            # Vice Rector Academic (IT + Library)
            {
                'username': 'vice.rector',
                'email': 'vice.rector.acad@example.test',
                'first_name': 'Dilshod',
                'last_name': 'Alimov',
                'role': Role.Codes.VICE_RECTOR,
                'department': None,
                'position': position_objects['VICE_RECTOR_ACAD'],
                'is_staff': False,
                'is_superuser': False,
            },
            # Vice Rector Finance (Finance + HR)
            {
                'username': 'vice.rector.finance',
                'email': 'vice.rector.fin@example.test',
                'first_name': 'Jamshid',
                'last_name': 'Karimov',
                'role': Role.Codes.VICE_RECTOR,
                'department': None,
                'position': position_objects['VICE_RECTOR_FIN'],
                'is_staff': False,
                'is_superuser': False,
            },
            # Department Heads
            {
                'username': 'department.head',
                'email': 'head.it@example.test',
                'first_name': 'Bekzod',
                'last_name': 'Nazarov',
                'role': Role.Codes.DEPARTMENT_HEAD,
                'department': department_objects['IT'],
                'position': position_objects['DEPT_HEAD'],
                'is_staff': False,
                'is_superuser': False,
            },
            {
                'username': 'head.library',
                'email': 'head.lib@example.test',
                'first_name': 'Gulnora',
                'last_name': 'Usmanova',
                'role': Role.Codes.DEPARTMENT_HEAD,
                'department': department_objects['LIB'],
                'position': position_objects['CHIEF_LIB'],
                'is_staff': False,
                'is_superuser': False,
            },
            {
                'username': 'head.finance',
                'email': 'head.fin@example.test',
                'first_name': 'Shavkat',
                'last_name': 'Toshmatov',
                'role': Role.Codes.DEPARTMENT_HEAD,
                'department': department_objects['FIN'],
                'position': position_objects['SNR_ACC'],
                'is_staff': False,
                'is_superuser': False,
            },
            # HR Manager (Phase 7 HR Authority)
            {
                'username': 'hr.manager',
                'email': 'hr.manager@example.test',
                'first_name': 'Dilshod',
                'last_name': 'Karimov',
                'role': Role.Codes.HR,
                'department': department_objects['HR'],
                'position': position_objects['HR_OFFICER'],
                'grade': grade_objects['G4'],
                'is_staff': False,
                'is_superuser': False,
            },
            # Employees
            {
                'username': 'employee.one',
                'email': 'dev.one@example.test',
                'first_name': 'Aziz',
                'last_name': 'Sobirov',
                'role': Role.Codes.EMPLOYEE,
                'department': department_objects['IT'],
                'position': position_objects['SNR_DEV'],
                'grade': grade_objects['G3'],
                'is_staff': False,
                'is_superuser': False,
            },
            {
                'username': 'employee.two',
                'email': 'lib.one@example.test',
                'first_name': 'Madina',
                'last_name': 'Ibragimova',
                'role': Role.Codes.EMPLOYEE,
                'department': department_objects['LIB'],
                'position': position_objects['LIBRARIAN'],
                'grade': grade_objects['G2'],
                'is_staff': False,
                'is_superuser': False,
            },
            {
                'username': 'employee.finance',
                'email': 'fin.one@example.test',
                'first_name': 'Otabek',
                'last_name': 'Yuldashev',
                'role': Role.Codes.EMPLOYEE,
                'department': department_objects['FIN'],
                'position': position_objects['SNR_ACC'],
                'grade': grade_objects['G3'],
                'is_staff': False,
                'is_superuser': False,
            },
            # Finance Manager (Phase 8 Finance Role — Operational Payroll Authority)
            {
                'username': 'finance.manager',
                'email': 'finance.manager@example.test',
                'first_name': 'Sarvar',
                'last_name': 'Xasanov',
                'role': Role.Codes.FINANCE,
                'department': department_objects['FIN'],
                'position': position_objects['FIN_MGR'],
                'grade': grade_objects['G4'],
                'is_staff': False,
                'is_superuser': False,
            },
        ]

        created_users = {}
        for data in users_data:
            role_code = data.pop('role')
            role = role_objects.get(role_code) if role_code else None
            username = data['username']
            user, created = User.objects.update_or_create(
                username=username,
                defaults=data,
            )
            if created or not user.check_password(demo_password):
                user.set_password(demo_password)
                user.save(update_fields=['password'])
            if role:
                user.roles.set([role])
            else:
                user.roles.clear()
            created_users[username] = user

        # Set reporting supervisor relationships
        created_users['employee.one'].supervisor = created_users['department.head']
        created_users['employee.one'].save(update_fields=['supervisor'])

        created_users['employee.two'].supervisor = created_users['head.library']
        created_users['employee.two'].save(update_fields=['supervisor'])

        created_users['department.head'].supervisor = created_users['vice.rector']
        created_users['department.head'].grade = grade_objects['G5']
        created_users['department.head'].save(update_fields=['supervisor', 'grade'])

        created_users['vice.rector'].supervisor = created_users['rector']
        created_users['vice.rector'].grade = grade_objects['G6']
        created_users['vice.rector'].save(update_fields=['supervisor', 'grade'])

        # Seed PayrollPermissionConfig for finance.manager (idempotent)
        fin_user = created_users.get('finance.manager')
        if fin_user:
            PayrollPermissionConfig.objects.update_or_create(
                user=fin_user,
                defaults={
                    'can_view_payroll': True,
                    'can_manage_salary': True,
                    'can_manage_compensation': True,
                    'can_calculate_payroll': True,
                    'can_create_adjustment': True,
                    'can_approve_payroll': False,
                    'can_mark_paid': False,
                    'can_view_payroll_reports': True,
                    'can_manage_tax_rules': True,
                    'can_manage_kpi_payroll_rules': True,
                },
            )


        # 5. ASSIGN DEPARTMENT HEADS
        assign_department_head(department_objects['IT'], created_users['department.head'], actor=created_users['rector'])
        assign_department_head(department_objects['LIB'], created_users['head.library'], actor=created_users['rector'])
        assign_department_head(department_objects['FIN'], created_users['head.finance'], actor=created_users['rector'])

        # 6. ASSIGN VICE RECTOR RESPONSIBILITIES
        vr_acad = created_users['vice.rector']
        assign_vice_rector_responsibility(vr_acad, department_objects['IT'], actor=created_users['rector'])
        assign_vice_rector_responsibility(vr_acad, department_objects['LIB'], actor=created_users['rector'])

        vr_fin = created_users['vice.rector.finance']
        assign_vice_rector_responsibility(vr_fin, department_objects['FIN'], actor=created_users['rector'])
        assign_vice_rector_responsibility(vr_fin, department_objects['HR'], actor=created_users['rector'])

        # 7. TASK TYPES
        task_types_data = [
            {'name': 'Website & Software Development', 'code': 'WEB_DEV', 'description': 'Software applications, portal enhancements, bug fixes'},
            {'name': 'Document Preparation', 'code': 'DOC_PREP', 'description': 'Policies, university orders, official regulations'},
            {'name': 'Research & Analytics', 'code': 'RESEARCH', 'description': 'Academic studies, curriculum revision, statistics'},
            {'name': 'Administrative Operations', 'code': 'ADMIN', 'description': 'Office tasks, recruitment, personnel affairs'},
            {'name': 'Financial Audit & Reporting', 'code': 'REPORT', 'description': 'Balance sheets, budget planning, audit reports'},
        ]
        created_types = {}
        for tt_data in task_types_data:
            created_types[tt_data['code']], _ = TaskType.objects.update_or_create(
                code=tt_data['code'],
                defaults=tt_data,
            )

        # 8. TASK TEMPLATES
        templates_data = [
            {
                'name': 'University Accreditation Report Preparation',
                'description': 'Standard multi-step procedure for preparing international accreditation documents and QA materials.',
                'task_type': created_types['DOC_PREP'],
                'default_priority': Task.Priority.HIGH,
                'default_complexity': Task.Complexity.CRITICAL,
                'default_duration_days': 30,
                'created_by': created_users['rector'],
            },
            {
                'name': 'Semester Examination Schedule Automation',
                'description': 'IT workflow to collect student groups, generate exam timetables, and publish to student portal.',
                'task_type': created_types['WEB_DEV'],
                'default_priority': Task.Priority.MEDIUM,
                'default_complexity': Task.Complexity.MEDIUM,
                'default_duration_days': 14,
                'created_by': created_users['vice.rector'],
            },
        ]
        for t_data in templates_data:
            TaskTemplate.objects.update_or_create(
                name=t_data['name'],
                defaults=t_data,
            )

        # 9. TASKS & WORKFLOW FOUNDATION
        today = timezone.now().date()

        # Task 1: Portal Development (IT - In Progress)
        t1, t1_created = Task.objects.update_or_create(
            title='Develop New University Website Portal',
            defaults={
                'description': 'Develop, test, and deploy modern university responsive web portal with student & faculty dashboards.',
                'creator': created_users['rector'],
                'responsible_department': department_objects['IT'],
                'task_type': created_types['WEB_DEV'],
                'priority': Task.Priority.HIGH,
                'complexity': Task.Complexity.CRITICAL,
                'status': Task.Status.IN_PROGRESS,
                'progress': 45,
                'start_date': today - timedelta(days=10),
                'deadline': today + timedelta(days=20),
            },
        )
        if t1_created or not t1.assignments.exists():
            assign_task(created_users['rector'], t1, [created_users['employee.one']], primary_user=created_users['employee.one'])
            create_subtask(created_users['rector'], t1, 'UI & Mobile Layout Design', status=SubTask.Status.DONE, progress=100)
            create_subtask(created_users['rector'], t1, 'Backend Database & API Setup', status=SubTask.Status.IN_PROGRESS, progress=60, assignee=created_users['employee.one'])
            create_subtask(created_users['rector'], t1, 'Automated Test Suite & Security QA', status=SubTask.Status.TODO, progress=0)

        # Task 2: Digital Library Catalog (Library - Assigned)
        t2, t2_created = Task.objects.update_or_create(
            title='Digital Library Catalog Migration',
            defaults={
                'description': 'Migrate 50,000 academic book and journal records into the new digital catalog system.',
                'creator': created_users['vice.rector'],
                'responsible_department': department_objects['LIB'],
                'task_type': created_types['WEB_DEV'],
                'priority': Task.Priority.MEDIUM,
                'complexity': Task.Complexity.MEDIUM,
                'status': Task.Status.ASSIGNED,
                'progress': 10,
                'start_date': today - timedelta(days=2),
                'deadline': today + timedelta(days=15),
            },
        )
        if t2_created or not t2.assignments.exists():
            assign_task(created_users['vice.rector'], t2, [created_users['employee.two']], primary_user=created_users['employee.two'])
            # Dependency: t2 depends on t1
            if not TaskDependency.objects.filter(task=t2, depends_on=t1).exists():
                add_dependency(created_users['vice.rector'], t2, t1)

        # Task 3: Financial Audit (Finance - In Progress, Overdue demo)
        t3, _ = Task.objects.update_or_create(
            title='Quarterly Budget & Financial Audit',
            defaults={
                'description': 'Compile Q2 audit reports, departmental expenditure reconciliation, and grant spending summaries.',
                'creator': created_users['vice.rector.finance'],
                'responsible_department': department_objects['FIN'],
                'task_type': created_types['REPORT'],
                'priority': Task.Priority.URGENT,
                'complexity': Task.Complexity.COMPLEX,
                'status': Task.Status.IN_PROGRESS,
                'progress': 75,
                'start_date': today - timedelta(days=15),
                'deadline': today - timedelta(days=2),  # intentionally overdue for testing
            },
        )
        if not t3.assignments.exists():
            assign_task(created_users['vice.rector.finance'], t3, [created_users['employee.finance']], primary_user=created_users['employee.finance'])

        # Task 4: HR Review (HR - Created, unassigned)
        Task.objects.update_or_create(
            title='Annual Faculty Performance Reviews & Appraisal',
            defaults={
                'description': 'Distribute evaluation rubrics to academic department heads and compile annual review packages.',
                'creator': created_users['rector'],
                'responsible_department': department_objects['HR'],
                'task_type': created_types['ADMIN'],
                'priority': Task.Priority.MEDIUM,
                'complexity': Task.Complexity.MEDIUM,
                'status': Task.Status.CREATED,
                'progress': 0,
                'start_date': today,
                'deadline': today + timedelta(days=25),
            },
        )

        # Task 5: Academic Curriculum (Academic - Draft)
        Task.objects.update_or_create(
            title='Curriculum Revision for AI & Data Science Minor',
            defaults={
                'description': 'Prepare draft syllabus, prerequisite mapping, and laboratory equipment requirements.',
                'creator': created_users['vice.rector'],
                'responsible_department': department_objects['ACAD'],
                'task_type': created_types['RESEARCH'],
                'priority': Task.Priority.HIGH,
                'complexity': Task.Complexity.COMPLEX,
                'status': Task.Status.DRAFT,
                'progress': 0,
                'start_date': today + timedelta(days=5),
                'deadline': today + timedelta(days=45),
            },
        )

        # Task 6: Completed Campus Network Upgrade
        t6, _ = Task.objects.update_or_create(
            title='Campus Network Upgrade — Fiber Optics Backbone',
            defaults={
                'description': 'Installed gigabit fiber optics across central campus buildings.',
                'creator': created_users['rector'],
                'responsible_department': department_objects['IT'],
                'task_type': created_types['WEB_DEV'],
                'priority': Task.Priority.URGENT,
                'complexity': Task.Complexity.COMPLEX,
                'status': Task.Status.COMPLETED,
                'progress': 100,
                'start_date': today - timedelta(days=30),
                'deadline': today - timedelta(days=5),
                'completed_at': timezone.now() - timedelta(days=5),
            },
        )
        if not t6.assignments.exists():
            assign_task(created_users['rector'], t6, [created_users['employee.one']], primary_user=created_users['employee.one'])
        # Ensure completed task assignments are marked approved / 100%
        for a in t6.assignments.all():
            a.assignment_status = TaskAssignment.AssignmentStatus.APPROVED
            a.progress = 100
            a.accepted_at = timezone.now() - timedelta(days=28)
            a.save(update_fields=['assignment_status', 'progress', 'accepted_at'])

        # Task 7: Archived Financial Report
        Task.objects.update_or_create(
            title='Archived 2025 Financial Balance Sheet & General Ledger',
            defaults={
                'description': 'Annual financial closure report for fiscal year 2025.',
                'creator': created_users['rector'],
                'responsible_department': department_objects['FIN'],
                'task_type': created_types['REPORT'],
                'priority': Task.Priority.LOW,
                'complexity': Task.Complexity.SIMPLE,
                'status': Task.Status.ARCHIVED,
                'progress': 100,
                'start_date': today - timedelta(days=120),
                'deadline': today - timedelta(days=60),
                'completed_at': timezone.now() - timedelta(days=60),
                'archived_at': timezone.now() - timedelta(days=30),
            },
        )

        # Task 8: New Incoming Task for IT Department (Incoming test case)
        t8, t8_created = Task.objects.update_or_create(
            title='Implement Automated Testing & CI/CD Pipeline',
            defaults={
                'description': 'Configure automated testing, linting checks, and continuous integration pipeline for all campus portals.',
                'creator': created_users['rector'],
                'responsible_department': department_objects['IT'],
                'task_type': created_types['WEB_DEV'],
                'priority': Task.Priority.HIGH,
                'complexity': Task.Complexity.MEDIUM,
                'status': Task.Status.ASSIGNED,
                'progress': 0,
                'start_date': today,
                'deadline': today + timedelta(days=18),
            },
        )
        if not t8.assignments.exists():
            assign_task(created_users['rector'], t8, [created_users['employee.one']], primary_user=created_users['employee.one'])
        else:
            t8_assign = t8.assignments.filter(user=created_users['employee.one']).first()
            if t8_assign and t8_assign.assignment_status == TaskAssignment.AssignmentStatus.ASSIGNED:
                # Keep in ASSIGNED state for Incoming test
                pass

        self.stdout.write(self.style.SUCCESS('Phase 3 development seed data populated successfully.'))
        self.stdout.write('Accounts (Password: ChangeMe12345!):')
        self.stdout.write(' - Rector: rector')
        self.stdout.write(' - Vice Rector Academic (IT, LIB): vice.rector')
        self.stdout.write(' - Vice Rector Finance (FIN, HR): vice.rector.finance')
        self.stdout.write(' - Department Head IT: department.head')
        self.stdout.write(' - Department Head Library: head.library')
        self.stdout.write(' - Department Head Finance: head.finance')
        self.stdout.write(' - Employee IT: employee.one')
        self.stdout.write(' - Employee Library: employee.two')
        self.stdout.write(' - Employee Finance: employee.finance')

        # =============================================================
        # PHASE 4 — Workflow seed: accepted, in-progress, submitted
        # =============================================================
        self.stdout.write('\nSeeding Phase 4 workflow states...')

        # emp1 (employee.one) already has assignment for t1 (Portal dev - IN_PROGRESS)
        # Simulate employee.one having ACCEPTED their t1 assignment
        try:
            t1_assignment = TaskAssignment.objects.filter(
                task=t1, user=created_users['employee.one']
            ).first()
            if t1_assignment and t1_assignment.assignment_status == TaskAssignment.AssignmentStatus.ASSIGNED:
                accept_assignment(created_users['employee.one'], t1_assignment)
                t1_assignment.refresh_from_db()
        except Exception:
            pass

        # employee.one: update progress to 45% and add a work note
        try:
            t1_assignment = TaskAssignment.objects.filter(
                task=t1, user=created_users['employee.one']
            ).first()
            if t1_assignment and t1_assignment.assignment_status == TaskAssignment.AssignmentStatus.IN_PROGRESS:
                update_assignment_progress(created_users['employee.one'], t1_assignment, 45)
                add_task_note(
                    created_users['employee.one'], t1, 
                    'Backend API structure has been completed. Starting on the frontend integration.',
                    assignment=t1_assignment
                )
        except Exception:
            pass

        # employee.two (Library) — simulate a submitted task (task 2)
        try:
            t2_assignment = TaskAssignment.objects.filter(
                task=t2, user=created_users['employee.two']
            ).first()
            if t2_assignment and t2_assignment.assignment_status == TaskAssignment.AssignmentStatus.ASSIGNED:
                accept_assignment(created_users['employee.two'], t2_assignment)
                t2_assignment.refresh_from_db()
            if t2_assignment and t2_assignment.assignment_status == TaskAssignment.AssignmentStatus.IN_PROGRESS:
                update_assignment_progress(created_users['employee.two'], t2_assignment, 100)
                add_task_note(
                    created_users['employee.two'], t2,
                    'Catalog migration completed. All 50,000 records transferred and validated.',
                    assignment=t2_assignment
                )
                submit_assignment(
                    created_users['employee.two'], t2_assignment,
                    'All 50,000 library catalog records have been successfully migrated to the new digital catalog system. Validation checks completed with 0 errors. System is ready for department head review.'
                )
        except Exception:
            pass

        # employee.finance — already has assignment for t3 (IN_PROGRESS, overdue)
        try:
            t3_assignment = TaskAssignment.objects.filter(
                task=t3, user=created_users['employee.finance']
            ).first()
            if t3_assignment and t3_assignment.assignment_status == TaskAssignment.AssignmentStatus.ASSIGNED:
                accept_assignment(created_users['employee.finance'], t3_assignment)
                t3_assignment.refresh_from_db()
            if t3_assignment and t3_assignment.assignment_status == TaskAssignment.AssignmentStatus.IN_PROGRESS:
                update_assignment_progress(created_users['employee.finance'], t3_assignment, 75)
                add_task_note(
                    created_users['employee.finance'], t3,
                    'Q2 audit report 75% complete. Pending final reconciliation from HR department.',
                    assignment=t3_assignment
                )
        except Exception:
            pass

        # =============================================================
        # PHASE 5 — Workflow seed: Second Approval, Rejection, Deadline Ext
        # =============================================================
        self.stdout.write('\nSeeding Phase 5 workflow states...')

        # Task 9: Second Approval task (Library task submitted and first-approved by head.library)
        t9, _ = Task.objects.update_or_create(
            title='Electronic Research Archive & Open Access Repository',
            defaults={
                'description': 'Integration of university research publications with international open access repositories.',
                'creator': created_users['vice.rector'],
                'responsible_department': department_objects['LIB'],
                'task_type': created_types['REPORT'],
                'priority': Task.Priority.HIGH,
                'complexity': Task.Complexity.COMPLEX,
                'status': Task.Status.IN_PROGRESS,
                'progress': 100,
                'start_date': today - timedelta(days=20),
                'deadline': today + timedelta(days=10),
            },
        )
        if not t9.assignments.exists():
            assign_task(created_users['vice.rector'], t9, [created_users['employee.two']], primary_user=created_users['employee.two'])
        
        t9_assign = t9.assignments.filter(user=created_users['employee.two']).first()
        if t9_assign:
            if t9_assign.assignment_status == TaskAssignment.AssignmentStatus.ASSIGNED:
                accept_assignment(created_users['employee.two'], t9_assign)
                t9_assign.refresh_from_db()
            if t9_assign.assignment_status == TaskAssignment.AssignmentStatus.IN_PROGRESS:
                update_assignment_progress(created_users['employee.two'], t9_assign, 100)
                sub9 = submit_assignment(
                    created_users['employee.two'], t9_assign,
                    'Research repository integration completed. 1,200 papers indexed according to OAI-PMH standards.'
                )
                t9_assign.refresh_from_db()
            if t9_assign.assignment_status == TaskAssignment.AssignmentStatus.SUBMITTED:
                first_approve_assignment(
                    created_users['head.library'], t9_assign,
                    notes='Department head review complete. All standards verified. Recommended for final approval.'
                )

        # Task 10: Rejected Task scenario (Finance task rejected during first approval)
        t10, _ = Task.objects.update_or_create(
            title='Quarterly Budget Expense Review — Science Grants',
            defaults={
                'description': 'Quarterly allocation and expense auditing for state research grant funds.',
                'creator': created_users['vice.rector.finance'],
                'responsible_department': department_objects['FIN'],
                'task_type': created_types['REPORT'],
                'priority': Task.Priority.MEDIUM,
                'complexity': Task.Complexity.MEDIUM,
                'status': Task.Status.IN_PROGRESS,
                'progress': 100,
                'start_date': today - timedelta(days=15),
                'deadline': today + timedelta(days=5),
            },
        )
        if not t10.assignments.exists():
            assign_task(created_users['vice.rector.finance'], t10, [created_users['employee.finance']], primary_user=created_users['employee.finance'])
        
        t10_assign = t10.assignments.filter(user=created_users['employee.finance']).first()
        if t10_assign:
            if t10_assign.assignment_status == TaskAssignment.AssignmentStatus.ASSIGNED:
                accept_assignment(created_users['employee.finance'], t10_assign)
                t10_assign.refresh_from_db()
            if t10_assign.assignment_status == TaskAssignment.AssignmentStatus.IN_PROGRESS:
                update_assignment_progress(created_users['employee.finance'], t10_assign, 100)
                submit_assignment(
                    created_users['employee.finance'], t10_assign,
                    'Expense review draft submitted with preliminary expense receipts.'
                )
                t10_assign.refresh_from_db()
            if t10_assign.assignment_status == TaskAssignment.AssignmentStatus.SUBMITTED:
                first_reject_assignment(
                    created_users['head.finance'], t10_assign,
                    reason='Supporting invoices for chemistry lab consumables are missing from section 4. Please attach all missing receipts and resubmit.'
                )

        # Deadline extension on Task 1 (Portal development)
        try:
            if not t1.deadline_extensions.exists():
                extend_task_deadline(
                    created_users['rector'], t1,
                    today + timedelta(days=25),
                    reason='Extended deadline due to additional requirements for single sign-on integration.'
                )
        except Exception:
            pass

        self.stdout.write(self.style.SUCCESS('Phase 5 workflow seed data populated successfully.'))

        # ===================================================================
        # 14. PHASE 6 — Files, Folders, Reports & Documents Seed Data
        # ===================================================================
        self.stdout.write('\nSeeding Phase 6 files, folders, reports & documents...')
        from django.core.files.uploadedfile import SimpleUploadedFile
        from files.models import TaskFile, TaskFolder, TaskReport
        from files.services import create_task_folder, create_task_report, upload_task_file

        # Folders on Task 1 (Portal development)
        fld_req, _ = TaskFolder.objects.get_or_create(
            task=t1, name='Requirements & Specs',
            defaults={'created_by': created_users['department.head']}
        )
        fld_dev, _ = TaskFolder.objects.get_or_create(
            task=t1, name='Development',
            defaults={'created_by': created_users['employee.one']}
        )
        fld_reports, _ = TaskFolder.objects.get_or_create(
            task=t1, name='Reports & Deliverables',
            defaults={'created_by': created_users['employee.one']}
        )

        # Files on Task 1
        if not TaskFile.objects.filter(task=t1).exists():
            # Architecture doc
            f1 = SimpleUploadedFile(
                'portal_architecture_v1.pdf',
                b'%PDF-1.4\n1 0 obj\n<< /Title (University Portal Architecture) >>\nendobj\n%%EOF',
                content_type='application/pdf'
            )
            upload_task_file(
                actor=created_users['employee.one'],
                task=t1,
                file_obj=f1,
                description='System architecture, component diagrams, and API specifications.',
                folder=fld_req,
                category=TaskFile.Category.REQUIREMENTS,
            )

            # Source archive
            f2 = SimpleUploadedFile(
                'portal_frontend_build.zip',
                b'PK\x03\x04\x14\x00\x00\x00\x08\x00Build bundle files placeholder',
                content_type='application/zip'
            )
            upload_task_file(
                actor=created_users['employee.one'],
                task=t1,
                file_obj=f2,
                description='Compiled frontend distribution bundle ready for deployment.',
                folder=fld_dev,
                category=TaskFile.Category.WORK_EVIDENCE,
            )

            # Benchmark report
            f3 = SimpleUploadedFile(
                'performance_benchmarks.xlsx',
                b'PK\x03\x04\x14\x00\x00\x00\x08\x00Excel benchmark sheet placeholder',
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            upload_task_file(
                actor=created_users['employee.one'],
                task=t1,
                file_obj=f3,
                description='Load testing and database query response time metrics.',
                folder=fld_reports,
                category=TaskFile.Category.REPORT_ATTACHMENT,
            )

        # Reports on Task 1
        if not TaskReport.objects.filter(task=t1).exists():
            create_task_report(
                actor=created_users['employee.one'],
                task=t1,
                title='Portal Core Architecture & Milestone 1 Progress Report',
                summary='Successfully implemented foundational authentication, organization hierarchy, and core task workflow engine.',
                completed_work='1. Designed responsive UI with Bootstrap 5.\n2. Implemented PostgreSQL database schemas.\n3. Added fine-grained role-based access control and IDOR protections.',
                results='All unit test suites passing (100%). Single sign-on authentication latency measured under 80ms.',
                reporting_period='Q3 2026',
                problems='Minor CSS dark-theme variable inconsistency identified during testing, subsequently resolved.',
                recommendations='Proceed with Phase 7 analytics and performance indexing.',
                conclusion='Task 1 milestone 1 deliverables meet all university engineering quality standards.',
                status=TaskReport.Status.APPROVED,
            )

        self.stdout.write(self.style.SUCCESS('Phase 6 files, folders, and reports seeded successfully.'))

        # ========================================================
        # PHASE 7: HR PERMISSIONS & KPI FOUNDATION
        # ========================================================
        # 1. HR Authority Configuration for hr.manager
        HRPermissionConfig.objects.update_or_create(
            user=created_users['hr.manager'],
            defaults={
                'can_view_employees': True,
                'can_create_employees': True,
                'can_edit_employees': True,
                'can_deactivate_employees': True,
                'can_assign_department': True,
                'can_assign_position': True,
                'can_assign_grade': True,
                'can_assign_supervisor': True,
                'can_manage_departments': False,
                'can_assign_department_head': False,
                'can_assign_vice_rector_responsibility': False,
                'can_view_kpi': True,
                'can_manage_kpi': True,
                'can_approve_kpi': True,
            }
        )

        # 2. KPI Categories
        kpi_cats = {
            'TASK_PERF': {'name': 'Task & Workflow Execution', 'order': 1, 'desc': 'Delivery of university directive tasks and assignments'},
            'QUALITY': {'name': 'Quality & Compliance Standards', 'order': 2, 'desc': 'Adherence to academic and software quality standards'},
            'DEADLINE': {'name': 'Deadline Compliance & Reliability', 'order': 3, 'desc': 'On-time milestone delivery and prompt task response'},
            'INNOVATION': {'name': 'Digital Innovation & Research', 'order': 4, 'desc': 'Creation of new academic modules and system optimizations'},
        }
        kpi_cat_objs = {}
        for code, c_data in kpi_cats.items():
            kpi_cat_objs[code], _ = KPICategory.objects.update_or_create(
                code=code,
                defaults={'name': c_data['name'], 'order': c_data['order'], 'description': c_data['desc'], 'is_active': True}
            )

        # 3. KPI Periods
        period_q1, _ = KPIPeriod.objects.update_or_create(
            code='2026-Q1',
            defaults={
                'name': '2026 Q1 Performance Cycle',
                'period_type': KPIPeriod.PeriodType.QUARTERLY,
                'start_date': timezone.now().date() - timedelta(days=60),
                'end_date': timezone.now().date() + timedelta(days=30),
                'status': KPIPeriod.Status.OPEN,
                'created_by': created_users['rector'],
                'is_active': True,
            }
        )
        period_q4, _ = KPIPeriod.objects.update_or_create(
            code='2025-Q4',
            defaults={
                'name': '2025 Q4 Performance Cycle',
                'period_type': KPIPeriod.PeriodType.QUARTERLY,
                'start_date': timezone.now().date() - timedelta(days=150),
                'end_date': timezone.now().date() - timedelta(days=61),
                'status': KPIPeriod.Status.CLOSED,
                'created_by': created_users['rector'],
                'approved_by': created_users['rector'],
                'is_active': True,
            }
        )

        # 4. KPI Definitions
        kpis = {
            'KPI_TASK_COMPLETION': {
                'name': 'Directive Task Completion Rate',
                'category': kpi_cat_objs['TASK_PERF'],
                'measurement_type': KPIDefinition.MeasurementType.PERCENTAGE,
                'target': 95.0,
                'weight': 35.0,
                'desc': 'Percentage of assigned tasks completed successfully',
            },
            'KPI_DEADLINE_ONTIME': {
                'name': 'On-Time Milestone Compliance',
                'category': kpi_cat_objs['DEADLINE'],
                'measurement_type': KPIDefinition.MeasurementType.PERCENTAGE,
                'target': 90.0,
                'weight': 25.0,
                'desc': 'Percentage of completed tasks finished before deadline',
            },
            'KPI_QUALITY_RATING': {
                'name': 'Peer & Manager Quality Review Rating',
                'category': kpi_cat_objs['QUALITY'],
                'measurement_type': KPIDefinition.MeasurementType.RATING,
                'target': 4.5,
                'weight': 25.0,
                'desc': 'Review rating (1-5 scale) assessed on submitted deliverables and evidence',
            },
            'KPI_DOCS': {
                'name': 'Technical & Process Documentation Completeness',
                'category': kpi_cat_objs['INNOVATION'],
                'measurement_type': KPIDefinition.MeasurementType.PERCENTAGE,
                'target': 100.0,
                'weight': 15.0,
                'desc': 'Completeness of architecture reports and system documentation',
            },
        }
        kpi_defs = {}
        for code, k_data in kpis.items():
            kpi_defs[code], _ = KPIDefinition.objects.update_or_create(
                code=code,
                defaults={
                    'name': k_data['name'],
                    'category': k_data['category'],
                    'measurement_type': k_data['measurement_type'],
                    'target_value': k_data['target'],
                    'weight': k_data['weight'],
                    'description': k_data['desc'],
                    'is_active': True,
                }
            )

        # 5. KPI Assignments & Results for 2026-Q1
        # Employee One (Senior Dev)
        a1, _ = KPIAssignment.objects.update_or_create(
            kpi=kpi_defs['KPI_TASK_COMPLETION'],
            user=created_users['employee.one'],
            period=period_q1,
            defaults={'target_value': 95.0, 'weight': 35.0, 'assigned_by': created_users['hr.manager']}
        )
        KPIResult.objects.update_or_create(
            assignment=a1,
            defaults={
                'actual_value': 100.0,
                'raw_score': 100.0,
                'weighted_score': 35.0,
                'status': KPIResult.Status.APPROVED,
                'evaluated_by': created_users['department.head'],
                'notes': 'Completed all assigned core architecture tasks ahead of time.',
            }
        )

        a2, _ = KPIAssignment.objects.update_or_create(
            kpi=kpi_defs['KPI_DEADLINE_ONTIME'],
            user=created_users['employee.one'],
            period=period_q1,
            defaults={'target_value': 90.0, 'weight': 25.0, 'assigned_by': created_users['hr.manager']}
        )
        KPIResult.objects.update_or_create(
            assignment=a2,
            defaults={
                'actual_value': 95.0,
                'raw_score': 100.0,
                'weighted_score': 25.0,
                'status': KPIResult.Status.APPROVED,
                'evaluated_by': created_users['department.head'],
                'notes': 'Zero overdue milestones recorded.',
            }
        )

        a3, _ = KPIAssignment.objects.update_or_create(
            kpi=kpi_defs['KPI_QUALITY_RATING'],
            user=created_users['employee.one'],
            period=period_q1,
            defaults={'target_value': 4.5, 'weight': 25.0, 'assigned_by': created_users['hr.manager']}
        )
        KPIResult.objects.update_or_create(
            assignment=a3,
            defaults={
                'actual_value': 4.8,
                'raw_score': 96.0,
                'weighted_score': 24.0,
                'status': KPIResult.Status.APPROVED,
                'evaluated_by': created_users['department.head'],
                'notes': 'High-quality architectural documentation and evidence attachments.',
            }
        )

        a4, _ = KPIAssignment.objects.update_or_create(
            kpi=kpi_defs['KPI_DOCS'],
            user=created_users['employee.one'],
            period=period_q1,
            defaults={'target_value': 100.0, 'weight': 15.0, 'assigned_by': created_users['hr.manager']}
        )
        KPIResult.objects.update_or_create(
            assignment=a4,
            defaults={
                'actual_value': 90.0,
                'raw_score': 90.0,
                'weighted_score': 13.5,
                'status': KPIResult.Status.REVIEWED,
                'evaluated_by': created_users['department.head'],
                'notes': 'Architecture report published.',
            }
        )

        # Employee Two (Librarian)
        a2_1, _ = KPIAssignment.objects.update_or_create(
            kpi=kpi_defs['KPI_TASK_COMPLETION'],
            user=created_users['employee.two'],
            period=period_q1,
            defaults={'target_value': 90.0, 'weight': 50.0, 'assigned_by': created_users['hr.manager']}
        )
        KPIResult.objects.update_or_create(
            assignment=a2_1,
            defaults={
                'actual_value': 88.0,
                'raw_score': 97.8,
                'weighted_score': 48.9,
                'status': KPIResult.Status.APPROVED,
                'evaluated_by': created_users['head.library'],
                'notes': 'Library catalog digitization in progress.',
            }
        )

        self.stdout.write(self.style.SUCCESS('Phase 7 HR, Employee Governance, and KPI Foundation seeded successfully.'))
        self.stdout.write('Phase 7 features ready:')
        self.stdout.write(' - HR Manager user created (username: hr.manager, password: ChangeMe12345!)')
        self.stdout.write(' - Employee grades G1-G6 created and assigned to staff')
        self.stdout.write(' - Supervisor reporting hierarchy established')
        self.stdout.write(' - Rector-configurable HR permissions initialized')
        self.stdout.write(' - KPI categories, 2026-Q1 period, indicator catalog, assignments, and results seeded')

        # -------------------------------------------------------------------
        # 10. PHASE 8: PAYROLL, COMPENSATION & PERFORMANCE-BASED SALARY
        # -------------------------------------------------------------------
        self.stdout.write('\nSeeding Phase 8 Payroll & Compensation System...')

        # Compensation Components
        comp_transport, _ = CompensationComponent.objects.update_or_create(
            code='COMP_TRANSPORT',
            defaults={
                'name': 'Transport Allowance',
                'component_type': CompensationComponent.ComponentType.ALLOWANCE,
                'calculation_type': CompensationComponent.CalculationType.FIXED,
                'default_value': Decimal('600000.00'),
                'is_taxable': False,
                'is_active': True,
                'description': 'Standard university monthly transport stipend.',
            }
        )

        comp_meal, _ = CompensationComponent.objects.update_or_create(
            code='COMP_MEAL',
            defaults={
                'name': 'Meal Subsidy',
                'component_type': CompensationComponent.ComponentType.ALLOWANCE,
                'calculation_type': CompensationComponent.CalculationType.FIXED,
                'default_value': Decimal('800000.00'),
                'is_taxable': False,
                'is_active': True,
                'description': 'Institutional campus dining subsidy.',
            }
        )

        comp_academic, _ = CompensationComponent.objects.update_or_create(
            code='COMP_ACAD_EXCELLENCE',
            defaults={
                'name': 'Academic Leadership Bonus',
                'component_type': CompensationComponent.ComponentType.BONUS,
                'calculation_type': CompensationComponent.CalculationType.FIXED,
                'default_value': Decimal('1500000.00'),
                'is_taxable': True,
                'is_active': True,
                'description': 'Incentive for leading departmental accreditation and digital workflows.',
            }
        )

        comp_union, _ = CompensationComponent.objects.update_or_create(
            code='COMP_UNION_DUES',
            defaults={
                'name': 'Staff Union Contribution',
                'component_type': CompensationComponent.ComponentType.DEDUCTION,
                'calculation_type': CompensationComponent.CalculationType.PERCENTAGE,
                'default_value': Decimal('1.00'),
                'is_taxable': False,
                'is_active': True,
                'description': '1% statutory university employee union welfare fund.',
            }
        )

        # Payroll Tax Rules (Configurable architecture)
        tax_pit, _ = PayrollTaxRule.objects.update_or_create(
            code='TAX_PIT_12',
            defaults={
                'name': 'Personal Income Tax (PIT)',
                'percentage': Decimal('12.00'),
                'fixed_amount': Decimal('0.00'),
                'applies_to': PayrollTaxRule.AppliesTo.TAXABLE_GROSS,
                'effective_from': timezone.datetime(2026, 1, 1).date(),
                'is_active': True,
            }
        )

        # KPI-to-Payroll Incentive Rules
        KPIPayrollRule.objects.update_or_create(
            name='Tier 1 Excellence (90% - 100%)',
            defaults={
                'min_score': Decimal('90.00'),
                'max_score': Decimal('100.00'),
                'bonus_type': KPIPayrollRule.BonusType.PERCENTAGE,
                'bonus_value': Decimal('15.00'),
                'effective_from': timezone.datetime(2026, 1, 1).date(),
                'is_active': True,
            }
        )
        KPIPayrollRule.objects.update_or_create(
            name='Tier 2 High Performance (80% - 89.99%)',
            defaults={
                'min_score': Decimal('80.00'),
                'max_score': Decimal('89.99'),
                'bonus_type': KPIPayrollRule.BonusType.PERCENTAGE,
                'bonus_value': Decimal('10.00'),
                'effective_from': timezone.datetime(2026, 1, 1).date(),
                'is_active': True,
            }
        )
        KPIPayrollRule.objects.update_or_create(
            name='Tier 3 Good Performance (70% - 79.99%)',
            defaults={
                'min_score': Decimal('70.00'),
                'max_score': Decimal('79.99'),
                'bonus_type': KPIPayrollRule.BonusType.PERCENTAGE,
                'bonus_value': Decimal('5.00'),
                'effective_from': timezone.datetime(2026, 1, 1).date(),
                'is_active': True,
            }
        )

        # Base Salaries & Historical Profiles
        salaries_data = [
            # Aziz Sobirov (Senior Developer, IT)
            {
                'user': created_users['employee.one'],
                'initial_salary': Decimal('12000000.00'),
                'current_salary': Decimal('14500000.00'),
                'initial_date': timezone.datetime(2026, 1, 1).date(),
                'current_date': timezone.datetime(2026, 7, 1).date(),
                'reason': 'Merit promotion to Senior Lead Architect',
            },
            # Madina Ibragimova (Librarian, Library)
            {
                'user': created_users['employee.two'],
                'initial_salary': Decimal('6500000.00'),
                'current_salary': Decimal('7800000.00'),
                'initial_date': timezone.datetime(2026, 1, 1).date(),
                'current_date': timezone.datetime(2026, 6, 1).date(),
                'reason': 'Grade G2 annual scale increment',
            },
            # Jasur Karimov / Otabek Yuldashev (Accountant, Finance)
            {
                'user': created_users['employee.finance'],
                'initial_salary': Decimal('8000000.00'),
                'current_salary': Decimal('9200000.00'),
                'initial_date': timezone.datetime(2026, 1, 1).date(),
                'current_date': timezone.datetime(2026, 8, 1).date(),
                'reason': 'Finance audit certification bonus and level adjustment',
            },
            # Bekzod Nazarov (Department Head, IT)
            {
                'user': created_users['department.head'],
                'initial_salary': Decimal('16000000.00'),
                'current_salary': Decimal('18500000.00'),
                'initial_date': timezone.datetime(2026, 1, 1).date(),
                'current_date': timezone.datetime(2026, 5, 1).date(),
                'reason': 'Department management responsibility index increase',
            },
            # Gulnora Usmanova (Department Head, Library)
            {
                'user': created_users['head.library'],
                'initial_salary': Decimal('11000000.00'),
                'current_salary': Decimal('12800000.00'),
                'initial_date': timezone.datetime(2026, 1, 1).date(),
                'current_date': timezone.datetime(2026, 4, 1).date(),
                'reason': 'Senior library chief compensation alignment',
            },
            # Shavkat Toshmatov (Department Head, Finance)
            {
                'user': created_users['head.finance'],
                'initial_salary': Decimal('14000000.00'),
                'current_salary': Decimal('16000000.00'),
                'initial_date': timezone.datetime(2026, 1, 1).date(),
                'current_date': timezone.datetime(2026, 6, 1).date(),
                'reason': 'Finance Department leadership performance review',
            },
            # Dilshod Karimov (HR Manager)
            {
                'user': created_users['hr.manager'],
                'initial_salary': Decimal('11500000.00'),
                'current_salary': Decimal('13200000.00'),
                'initial_date': timezone.datetime(2026, 1, 1).date(),
                'current_date': timezone.datetime(2026, 7, 1).date(),
                'reason': 'HR governance expansion & grade G4 adjustment',
            },
        ]

        admin_actor = created_users['superadmin']
        rector_actor = created_users['rector']

        for item in salaries_data:
            target_u = item['user']
            # If no profile exists, create initial and then update
            if not SalaryProfile.objects.filter(user=target_u).exists():
                # Initial Profile
                create_salary_profile(
                    actor=admin_actor,
                    user=target_u,
                    base_salary=item['initial_salary'],
                    effective_from=item['initial_date'],
                    notes='Initial institutional placement salary profile',
                )
                # Updated Profile with History
                create_salary_profile(
                    actor=rector_actor,
                    user=target_u,
                    base_salary=item['current_salary'],
                    effective_from=item['current_date'],
                    notes=item['reason'],
                )

        # Payroll Periods
        # Period 1: October 2026 (APPROVED & Partially PAID)
        period_oct, _ = PayrollPeriod.objects.update_or_create(
            code='2026-10',
            defaults={
                'name': 'October 2026 Monthly Payroll',
                'period_type': PayrollPeriod.PeriodType.MONTHLY,
                'start_date': timezone.datetime(2026, 10, 1).date(),
                'end_date': timezone.datetime(2026, 10, 31).date(),
                'status': PayrollPeriod.Status.OPEN,
                'created_by': rector_actor,
            }
        )

        # Run period calculation for October 2026
        calculate_period_payroll(period_oct, actor=rector_actor)

        # Approve October period and mark several as PAID
        approve_period_payroll(rector_actor, period_oct)

        rec_aziz = PayrollRecord.objects.filter(period=period_oct, employee=created_users['employee.one']).first()
        if rec_aziz:
            mark_payroll_paid(rector_actor, rec_aziz, payment_reference='BANK-TR-202610-001')

        rec_gulnora = PayrollRecord.objects.filter(period=period_oct, employee=created_users['head.library']).first()
        if rec_gulnora:
            mark_payroll_paid(rector_actor, rec_gulnora, payment_reference='BANK-TR-202610-002')

        rec_shavkat = PayrollRecord.objects.filter(period=period_oct, employee=created_users['head.finance']).first()
        if rec_shavkat:
            mark_payroll_paid(rector_actor, rec_shavkat, payment_reference='BANK-TR-202610-003')

        # Period 2: November 2026 (OPEN / In-Progress Cycle)
        period_nov, _ = PayrollPeriod.objects.update_or_create(
            code='2026-11',
            defaults={
                'name': 'November 2026 Monthly Payroll',
                'period_type': PayrollPeriod.PeriodType.MONTHLY,
                'start_date': timezone.datetime(2026, 11, 1).date(),
                'end_date': timezone.datetime(2026, 11, 30).date(),
                'status': PayrollPeriod.Status.OPEN,
                'created_by': rector_actor,
            }
        )
        # Phase 9: Demo completed task awaiting electronic signature
        demo_task, _ = Task.objects.update_or_create(
            task_number='TM-000999',
            defaults={
                'title': 'University Digital Infrastructure & Security Audit 2026',
                'description': 'Comprehensive cybersecurity assessment, network architecture review, and university compliance audit.',
                'creator': created_users['rector'],
                'responsible_department': department_objects['IT'],
                'priority': Task.Priority.HIGH,
                'complexity': Task.Complexity.COMPLEX,
                'status': Task.Status.COMPLETED,
                'progress': 100,
                'deadline': timezone.now().date() + timedelta(days=14),
                'completed_at': timezone.now(),
            }
        )

        demo_assignment, _ = TaskAssignment.objects.update_or_create(
            task=demo_task,
            user=created_users['employee.one'],
            defaults={
                'assigned_by': created_users['department.head'],
                'is_primary': True,
                'assignment_status': TaskAssignment.AssignmentStatus.APPROVED,
                'accepted_at': timezone.now() - timedelta(days=3),
                'progress': 100,
            }
        )

        from tasks.models import TaskApproval, TaskSubmission
        demo_sub, _ = TaskSubmission.objects.update_or_create(
            task=demo_task,
            assignment=demo_assignment,
            version=1,
            defaults={
                'submitted_by': created_users['employee.one'],
                'submission_text': 'All IT infrastructure penetration tests and security compliance checks have been performed with zero critical vulnerabilities.',
                'status': TaskSubmission.SubmissionStatus.FINAL_APPROVED,
                'submitted_at': timezone.now() - timedelta(days=1),
            }
        )

        # First approval by Department Head
        TaskApproval.objects.update_or_create(
            task=demo_task,
            assignment=demo_assignment,
            stage=TaskApproval.Stage.FIRST_APPROVAL,
            defaults={
                'submission': demo_sub,
                'decision': TaskApproval.Decision.APPROVED,
                'actor': created_users['department.head'],
                'actor_role_code': 'DEPARTMENT_HEAD',
                'reason': 'Technical deliverables inspected and approved by IT Department Head.',
            }
        )

        # Final approval by Rector
        TaskApproval.objects.update_or_create(
            task=demo_task,
            assignment=demo_assignment,
            stage=TaskApproval.Stage.FINAL_APPROVAL,
            defaults={
                'submission': demo_sub,
                'decision': TaskApproval.Decision.APPROVED,
                'actor': created_users['rector'],
                'actor_role_code': 'RECTOR',
                'reason': 'University-wide operational compliance confirmed. Approved for electronic signing.',
            }
        )

        # =====================================================================
        # PHASE 11: WORKFLOW AUTOMATION & SLA POLICIES
        # =====================================================================
        from automation.models import SLAPolicy, EscalationPolicy, RecurringTaskRule, AutomationRule
        
        sla_urgent, _ = SLAPolicy.objects.update_or_create(
            name="Urgent Priority SLA",
            defaults={
                'priority': Task.Priority.CRITICAL,
                'response_time_hours': 2,
                'resolution_time_hours': 24,
                'auto_escalate': True,
                'is_active': True,
            }
        )

        sla_standard, _ = SLAPolicy.objects.update_or_create(
            name="Standard Departmental SLA",
            defaults={
                'priority': Task.Priority.MEDIUM,
                'response_time_hours': 12,
                'resolution_time_hours': 72,
                'auto_escalate': False,
                'is_active': True,
            }
        )

        escalation_rule, _ = EscalationPolicy.objects.update_or_create(
            name="Overdue Task Executive Escalation",
            defaults={
                'sla_policy': sla_urgent,
                'trigger_event': EscalationPolicy.TriggerEvent.DEADLINE_BREACHED,
                'escalate_to_role': role_objects[Role.Codes.VICE_RECTOR],
                'notify_rector': True,
                'action': EscalationPolicy.Action.NOTIFY_AND_REASSIGN,
                'is_active': True,
            }
        )

        recurring_rule, _ = RecurringTaskRule.objects.update_or_create(
            name="Weekly Department Status Report",
            defaults={
                'title_template': "Weekly Status Briefing - {date}",
                'frequency': RecurringTaskRule.Frequency.WEEKLY,
                'creator': created_users['rector'],
                'department': Department.objects.filter(is_active=True).first(),
                'assigned_role': role_objects[Role.Codes.DEPARTMENT_HEAD],
                'days_to_due': 3,
                'is_active': True,
            }
        )

        auto_rule, _ = AutomationRule.objects.update_or_create(
            name="Auto-Notify Vice Rector on Critical Task",
            defaults={
                'trigger_type': AutomationRule.TriggerType.TASK_CREATED,
                'condition_field': 'priority',
                'condition_operator': 'equals',
                'condition_value': Task.Priority.CRITICAL,
                'action_type': AutomationRule.ActionType.NOTIFY_USER,
                'action_payload': {'recipient_role': 'VICE_RECTOR', 'message': 'A critical task requires your attention.'},
                'is_active': True,
            }
        )

        # =====================================================================
        # PHASE 12: COMMUNICATION & INTEGRATIONS
        # =====================================================================
        from communication.models import NotificationPreference, TelegramProfile, ExternalIntegration, IntegrationSyncLog

        for u in created_users.values():
            NotificationPreference.objects.update_or_create(
                user=u,
                defaults={
                    'email_enabled': True,
                    'telegram_enabled': True,
                    'push_enabled': True,
                    'task_assignments': True,
                    'task_status_changes': True,
                    'task_reminders': True,
                    'sla_breaches': True,
                }
            )

        TelegramProfile.objects.update_or_create(
            user=created_users['rector'],
            defaults={
                'telegram_chat_id': '123456789',
                'telegram_username': 'rector_official',
                'is_verified': True,
            }
        )

        hemis_integ, _ = ExternalIntegration.objects.update_or_create(
            name="HEMIS University System",
            integration_type=ExternalIntegration.IntegrationType.HEMIS,
            defaults={
                'endpoint_url': "https://hemis.university.uz/api/v1",
                'is_active': True,
                'sync_frequency_minutes': 60,
            }
        )
        IntegrationSyncLog.objects.create(
            integration=hemis_integ,
            sync_type="DEPARTMENTS_SYNC",
            status=IntegrationSyncLog.Status.SUCCESS,
            items_processed=12,
            details="HEMIS institutional departments synchronized successfully."
        )

        moodle_integ, _ = ExternalIntegration.objects.update_or_create(
            name="Moodle LMS Portal",
            integration_type=ExternalIntegration.IntegrationType.MOODLE,
            defaults={
                'endpoint_url': "https://lms.university.uz/webservice/rest/server.php",
                'is_active': True,
                'sync_frequency_minutes': 120,
            }
        )

        # =====================================================================
        # PHASE 13: ADVANCED OPERATIONS & UNIVERSITY DOCUMENTS
        # =====================================================================
        from operations.models import RequestCategory, RequestType, UniversityRequest, RequestApprovalStep, UniversityDocument, DocumentVersion

        cat_it, _ = RequestCategory.objects.update_or_create(
            code="IT_INFRA",
            defaults={'name': "IT & Digital Infrastructure", 'icon': "bi-laptop", 'is_active': True}
        )
        cat_acad, _ = RequestCategory.objects.update_or_create(
            code="ACADEMIC",
            defaults={'name': "Academic Affairs & Research", 'icon': "bi-journal-bookmark", 'is_active': True}
        )

        req_type_eq, _ = RequestType.objects.update_or_create(
            code="EQ_PROCURE",
            defaults={
                'category': cat_it,
                'name': "IT Equipment & Hardware Requisition",
                'approval_flow_type': RequestType.ApprovalFlowType.SEQUENTIAL,
                'is_active': True,
            }
        )

        dept_it = Department.objects.filter(is_active=True).first()
        demo_req, _ = UniversityRequest.objects.update_or_create(
            request_number="REQ-2026-0001",
            defaults={
                'request_type': req_type_eq,
                'requester': created_users['employee'],
                'department': dept_it,
                'subject': "High-Performance Workstation for AI Lab",
                'description': "Requesting upgraded hardware for running machine learning tasks in departmental research.",
                'priority': UniversityRequest.Priority.HIGH,
                'status': UniversityRequest.Status.IN_REVIEW,
                'current_stage_order': 1,
            }
        )
        RequestApprovalStep.objects.update_or_create(
            request=demo_req,
            step_order=1,
            defaults={
                'approver_role': role_objects[Role.Codes.DEPARTMENT_HEAD],
                'assigned_approver': created_users['department.head'],
                'status': RequestApprovalStep.Status.APPROVED,
                'decision_comments': "Approved for departmental IT research allocation.",
                'action_taken_at': timezone.now(),
            }
        )
        RequestApprovalStep.objects.update_or_create(
            request=demo_req,
            step_order=2,
            defaults={
                'approver_role': role_objects[Role.Codes.VICE_RECTOR],
                'assigned_approver': created_users['vice.rector'],
                'status': RequestApprovalStep.Status.PENDING,
            }
        )

        doc_pol, _ = UniversityDocument.objects.update_or_create(
            doc_number="DOC-POL-2026",
            defaults={
                'title': "University Task & Quality Governance Policy 2026",
                'category': UniversityDocument.DocCategory.REGULATION,
                'owner_department': dept_it,
                'created_by': created_users['rector'],
                'status': UniversityDocument.Status.APPROVED,
                'description': "Official operational regulation governing task workflows, SLA metrics, and electronic signatures.",
            }
        )
        DocumentVersion.objects.update_or_create(
            document=doc_pol,
            version_number=1,
            defaults={
                'changelog': "Initial institutional adoption release.",
                'is_current': True,
            }
        )

        # =====================================================================
        # PHASE 14: AI ASSISTANT & MANAGEMENT INTELLIGENCE
        # =====================================================================
        from ai_assistant.models import ManagementRiskIndicator, ExecutiveBriefing

        ManagementRiskIndicator.objects.update_or_create(
            title="Approaching Academic Exam Tasks Peak",
            defaults={
                'category': ManagementRiskIndicator.Category.DEADLINE_OVERFLOW,
                'severity': ManagementRiskIndicator.Severity.MEDIUM,
                'status': ManagementRiskIndicator.Status.ACTIVE,
                'description': "15 major examination review tasks are scheduled within a 48-hour window across 3 faculties.",
                'suggested_mitigation': "Pre-assign grading delegates and extend department SLA buffers.",
                'department': dept_it,
            }
        )

        ManagementRiskIndicator.objects.update_or_create(
            title="Single Point of Dependency in IT Approvals",
            defaults={
                'category': ManagementRiskIndicator.Category.BOTTLENECK,
                'severity': ManagementRiskIndicator.Severity.HIGH,
                'status': ManagementRiskIndicator.Status.ACTIVE,
                'description': "Department Head has 8 pending first approvals awaiting action over 3 business days.",
                'suggested_mitigation': "Enable auto-escalation or designate temporary acting deputy.",
                'department': dept_it,
            }
        )

        ExecutiveBriefing.objects.update_or_create(
            title="Executive Operational Pulse — Week 36",
            briefing_type=ExecutiveBriefing.BriefingType.WEEKLY_EXECUTIVE,
            defaults={
                'period_start': timezone.now().date() - timedelta(days=7),
                'period_end': timezone.now().date(),
                'generated_for': created_users['rector'],
                'metrics_summary': {
                    'total_tasks': 42,
                    'completion_rate_pct': 92.4,
                    'sla_adherence_pct': 96.0,
                    'active_requests': 7,
                    'payroll_status': 'Disbursed',
                },
                'executive_notes': "Overall university task performance is steady. IT and Academic departments maintain above 90% SLA adherence.",
            }
        )

        self.stdout.write(self.style.SUCCESS('Phase 9 Demo Completed Task TM-000999 ready for Electronic Signing testing.'))
        self.stdout.write(self.style.SUCCESS('Phase 8 Payroll & Compensation System seeded successfully.'))
        self.stdout.write(self.style.SUCCESS('Phases 11-14 Enterprise modules seeded (SLA, Automation, Integrations, Requests, AI Intelligence).'))
        self.stdout.write('Phase 15 Production Readiness and Hardening complete.')





