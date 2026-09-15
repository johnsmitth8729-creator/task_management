from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role, User
from core.models import AuditLog
from hr.forms import EmployeeCreateForm, EmployeeEditForm
from hr.models import EmployeeGrade, HRPermissionConfig
from hr.services import (
    activate_employee,
    configure_hr_authority,
    create_employee,
    create_grade,
    deactivate_employee,
    get_eligible_supervisors,
    get_hr_permission,
    update_employee,
    update_grade,
    validate_supervisor_assignment,
)
from organization.models import Department, DepartmentResponsibility, Position


class HREmployeeGovernanceTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Roles
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.vice_rector_role = Role.objects.create(code=Role.Codes.VICE_RECTOR, name='Vice Rector')
        self.hr_role = Role.objects.create(code=Role.Codes.HR, name='HR Manager')
        self.dept_head_role = Role.objects.create(code=Role.Codes.DEPARTMENT_HEAD, name='Department Head')
        self.employee_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

        # Departments & Positions
        self.it_dept = Department.objects.create(name='IT Department', code='IT')
        self.lib_dept = Department.objects.create(name='Library', code='LIB')

        self.dev_pos = Position.objects.create(
            name='Software Engineer', code='DEV', department=self.it_dept, can_supervise=False
        )
        self.lead_pos = Position.objects.create(
            name='IT Team Lead', code='LEAD_DEV', department=self.it_dept, can_supervise=True
        )
        self.lib_pos = Position.objects.create(
            name='Librarian', code='LIB_STAFF', department=self.lib_dept, can_supervise=False
        )
        self.chief_lib_pos = Position.objects.create(
            name='Chief Librarian', code='CHIEF_LIB', department=self.lib_dept, can_supervise=True
        )

        # Grades
        self.grade_g3 = EmployeeGrade.objects.create(name='Senior Specialist', code='G3', rank=3)
        self.grade_g4 = EmployeeGrade.objects.create(name='Lead Specialist', code='G4', rank=4)
        self.grade_g5 = EmployeeGrade.objects.create(name='Principal Specialist', code='G5', rank=5)

        # Users
        self.superadmin = User.objects.create_user(
            username='superadmin', email='superadmin@test.com', password='password123', is_superuser=True, is_staff=True
        )

        self.rector = User.objects.create_user(username='rector', email='rector@test.com', password='password123')
        self.rector.roles.add(self.rector_role)

        self.vice_rector = User.objects.create_user(username='vice_rector', email='vr@test.com', password='password123')
        self.vice_rector.roles.add(self.vice_rector_role)
        DepartmentResponsibility.objects.create(vice_rector=self.vice_rector, department=self.it_dept, is_active=True)

        self.hr_user = User.objects.create_user(username='hr_user', email='hr@test.com', password='password123', department=self.it_dept)
        self.hr_user.roles.add(self.hr_role)

        self.dept_head = User.objects.create_user(
            username='dept_head', email='head@test.com', password='password123', department=self.it_dept, position=self.lead_pos
        )
        self.dept_head.roles.add(self.dept_head_role)
        self.it_dept.head = self.dept_head
        self.it_dept.save()

        self.emp1 = User.objects.create_user(
            username='emp1', email='emp1@test.com', password='password123', department=self.it_dept, position=self.dev_pos, grade=self.grade_g3, supervisor=self.dept_head
        )
        self.emp1.roles.add(self.employee_role)

        self.emp2 = User.objects.create_user(
            username='emp2', email='emp2@test.com', password='password123', department=self.lib_dept, position=self.lib_pos, grade=self.grade_g5
        )
        self.emp2.roles.add(self.employee_role)

    def test_create_employee_service(self):
        HRPermissionConfig.objects.create(
            user=self.hr_user,
            can_create_employees=True,
            can_assign_department=True,
            can_assign_position=True,
            can_assign_grade=True,
            can_assign_supervisor=True,
        )
        new_emp = create_employee(
            actor=self.hr_user,
            data={
                'username': 'new_dev',
                'email': 'new_dev@test.com',
                'first_name': 'John',
                'last_name': 'Doe',
                'department': self.it_dept,
                'position': self.dev_pos,
                'grade': self.grade_g3,
                'supervisor': self.dept_head,
            }
        )
        self.assertEqual(new_emp.username, 'new_dev')
        self.assertEqual(new_emp.department, self.it_dept)
        self.assertEqual(new_emp.grade, self.grade_g3)
        self.assertEqual(new_emp.supervisor, self.dept_head)
        self.assertTrue(new_emp.is_active)

        # Audit log created
        log = AuditLog.objects.filter(action=AuditLog.Actions.USER_CREATED, actor=self.hr_user).first()
        self.assertIsNotNone(log)

    def test_hr_permission_guard_on_create(self):
        HRPermissionConfig.objects.create(user=self.hr_user, can_create_employees=False)
        self.client.login(username='hr_user', password='password123')
        resp = self.client.get(reverse('hr:employee_create'))
        self.assertEqual(resp.status_code, 403)

    def test_update_employee_and_audit(self):
        HRPermissionConfig.objects.create(user=self.hr_user, can_edit_employees=True, can_assign_grade=True, can_assign_department=True)
        update_employee(
            actor=self.hr_user,
            user=self.emp1,
            data={'grade': self.grade_g4, 'first_name': 'Azizbek'}
        )
        self.emp1.refresh_from_db()
        self.assertEqual(self.emp1.grade, self.grade_g4)
        self.assertEqual(self.emp1.first_name, 'Azizbek')

        # Grade change audit
        log = AuditLog.objects.filter(action=AuditLog.Actions.EMPLOYEE_GRADE_CHANGED, actor=self.hr_user).first()
        self.assertIsNotNone(log)

    def test_soft_deactivate_and_activate_employee(self):
        HRPermissionConfig.objects.create(user=self.hr_user, can_deactivate_employees=True)
        deactivate_employee(actor=self.hr_user, user=self.emp1)
        self.emp1.refresh_from_db()
        self.assertFalse(self.emp1.is_active)
        self.assertEqual(self.emp1.employment_status, User.EmploymentStatus.INACTIVE)

        # Check activation
        activate_employee(actor=self.hr_user, user=self.emp1)
        self.emp1.refresh_from_db()
        self.assertTrue(self.emp1.is_active)
        self.assertEqual(self.emp1.employment_status, User.EmploymentStatus.ACTIVE)

    def test_rector_hr_permission_configuration(self):
        self.client.login(username='rector', password='password123')
        resp = self.client.get(reverse('hr:permissions_config'))
        self.assertEqual(resp.status_code, 200)

        post_data = {
            'user_id': str(self.hr_user.id),
            'can_view_employees': 'on',
            'can_create_employees': 'on',
            'can_edit_employees': 'on',
            'can_deactivate_employees': 'on',
            'can_assign_grade': 'on',
        }
        resp = self.client.post(reverse('hr:permissions_config'), post_data)
        self.assertEqual(resp.status_code, 302)

        authority = HRPermissionConfig.objects.get(user=self.hr_user)
        self.assertTrue(authority.can_create_employees)
        self.assertTrue(authority.can_deactivate_employees)

        # Ordinary employee accessing permissions config is rejected with 403
        self.client.login(username='emp1', password='password123')
        resp = self.client.get(reverse('hr:permissions_config'))
        self.assertEqual(resp.status_code, 403)

    def test_employee_profile_idor_protection(self):
        self.client.login(username='emp1', password='password123')
        resp = self.client.get(reverse('hr:employee_profile', kwargs={'pk': self.emp1.pk}))
        self.assertEqual(resp.status_code, 200)

        # Employee 1 trying to view Employee 2 (different dept) returns 403
        resp = self.client.get(reverse('hr:employee_profile', kwargs={'pk': self.emp2.pk}))
        self.assertEqual(resp.status_code, 403)

    # -------------------------------------------------------------------------
    # SUPERVISOR ELIGIBILITY & HIERARCHY TESTS
    # -------------------------------------------------------------------------

    def test_ordinary_employee_cannot_be_supervisor(self):
        # emp2 is a G5 employee but position has can_supervise=False and is ordinary employee
        self.assertFalse(self.emp2.can_supervise)
        with self.assertRaises(ValidationError):
            validate_supervisor_assignment(self.emp1, self.emp2, self.it_dept)

    def test_management_position_employee_can_be_supervisor(self):
        # dept_head has can_supervise=True and is Department Head
        self.assertTrue(self.dept_head.can_supervise)
        # Should not raise exception
        validate_supervisor_assignment(self.emp1, self.dept_head, self.it_dept)

    def test_superadmin_cannot_be_supervisor(self):
        # Technical Superadmin cannot supervise employees
        self.assertFalse(self.superadmin.can_supervise)
        with self.assertRaises(ValidationError):
            validate_supervisor_assignment(self.emp1, self.superadmin, self.it_dept)

    def test_inactive_and_terminated_employee_cannot_be_supervisor(self):
        # Inactive manager cannot supervise
        self.dept_head.is_active = False
        self.dept_head.save()
        with self.assertRaises(ValidationError):
            validate_supervisor_assignment(self.emp1, self.dept_head, self.it_dept)

        # Terminated status cannot supervise
        self.dept_head.is_active = True
        self.dept_head.employment_status = User.EmploymentStatus.TERMINATED
        self.dept_head.save()
        with self.assertRaises(ValidationError):
            validate_supervisor_assignment(self.emp1, self.dept_head, self.it_dept)

    def test_user_cannot_supervise_himself(self):
        with self.assertRaises(ValidationError):
            validate_supervisor_assignment(self.dept_head, self.dept_head, self.it_dept)

    def test_cyclic_supervisor_hierarchy_rejected(self):
        # Team lead reports to Dept Head
        lead_user = User.objects.create_user(
            username='lead_user', email='lead@test.com', password='password123',
            department=self.it_dept, position=self.lead_pos, supervisor=self.dept_head
        )
        lead_user.roles.add(self.employee_role)

        # Attempting to make Dept Head report to lead_user creates a cycle:
        # Dept Head -> lead_user -> Dept Head
        with self.assertRaises(ValidationError):
            validate_supervisor_assignment(self.dept_head, lead_user, self.it_dept)

    def test_incompatible_department_supervisor_rejected(self):
        # Chief Librarian of Library cannot supervise an IT employee
        chief_lib = User.objects.create_user(
            username='chief_lib', email='chief_lib@test.com', password='password123',
            department=self.lib_dept, position=self.chief_lib_pos
        )
        chief_lib.roles.add(self.dept_head_role)

        with self.assertRaises(ValidationError):
            validate_supervisor_assignment(self.emp1, chief_lib, self.it_dept)

    def test_department_options_api(self):
        HRPermissionConfig.objects.create(user=self.hr_user, can_create_employees=True)
        self.client.login(username='hr_user', password='password123')

        resp = self.client.get(reverse('hr:api_department_options'), {'department_id': str(self.it_dept.id)})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # Should list IT compatible positions
        pos_names = [p['name'] for p in data['positions']]
        self.assertIn('Software Engineer (IT)', pos_names)

        # Should list eligible supervisors (dept_head, vice_rector, rector) and NOT ordinary employees (emp1, emp2)
        sup_ids = [s['id'] for s in data['supervisors']]
        self.assertIn(str(self.dept_head.id), sup_ids)
        self.assertIn(str(self.vice_rector.id), sup_ids)
        self.assertIn(str(self.rector.id), sup_ids)
        self.assertNotIn(str(self.emp1.id), sup_ids)
        self.assertNotIn(str(self.emp2.id), sup_ids)
        self.assertNotIn(str(self.superadmin.id), sup_ids)

    def test_form_supervisor_queryset_excludes_ordinary_employees(self):
        form = EmployeeCreateForm(department=self.it_dept)
        sup_queryset_ids = list(form.fields['supervisor'].queryset.values_list('id', flat=True))

        self.assertIn(self.dept_head.id, sup_queryset_ids)
        self.assertNotIn(self.emp1.id, sup_queryset_ids)
        self.assertNotIn(self.emp2.id, sup_queryset_ids)
        self.assertNotIn(self.superadmin.id, sup_queryset_ids)
