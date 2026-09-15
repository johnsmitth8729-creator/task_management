import uuid
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role
from organization.models import ActingRectorDelegation, Department, DepartmentResponsibility, Position
from organization.services import (
    assign_acting_rector,
    assign_department_head,
    assign_rector,
    assign_vice_rector_responsibility,
    remove_vice_rector_responsibility,
    revoke_acting_rector,
)

User = get_user_model()


class OrganizationModelAndServiceTests(TestCase):
    def setUp(self):
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.vr_role = Role.objects.create(code=Role.Codes.VICE_RECTOR, name='Vice Rector')
        self.head_role = Role.objects.create(code=Role.Codes.DEPARTMENT_HEAD, name='Department Head')
        self.emp_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

        self.rector = User.objects.create_user(
            username='rector', email='rector@example.com', password='Password123!',
        )
        self.rector.roles.add(self.rector_role)

        self.vr_acad = User.objects.create_user(
            username='vr.acad', email='vr.acad@example.com', password='Password123!',
        )
        self.vr_acad.roles.add(self.vr_role)

        self.dept_it = Department.objects.create(name='IT Department', code='IT')
        self.dept_fin = Department.objects.create(name='Finance Department', code='FIN')

        self.user_it = User.objects.create_user(
            username='user.it', email='user.it@example.com', password='Password123!',
            department=self.dept_it,
        )
        self.user_it.roles.add(self.head_role)

    def test_department_head_assignment_service(self):
        assign_department_head(self.dept_it, self.user_it, actor=self.rector)
        self.dept_it.refresh_from_db()
        self.assertEqual(self.dept_it.head, self.user_it)
        self.assertTrue(self.user_it.is_department_head)

    def test_single_department_head_rule_enforced(self):
        # 1. user_it is initial head
        assign_department_head(self.dept_it, self.user_it, actor=self.rector)
        self.dept_it.refresh_from_db()
        self.assertEqual(self.dept_it.head, self.user_it)
        self.assertTrue(self.user_it.is_department_head)

        # 2. Assign new user as head
        user_new = User.objects.create_user(
            username='user.new', email='user.new@example.com', password='Password123!',
            department=self.dept_it,
        )
        assign_department_head(self.dept_it, user_new, actor=self.rector)
        self.dept_it.refresh_from_db()
        self.user_it.refresh_from_db()
        user_new.refresh_from_db()

        # Check only user_new is head
        self.assertEqual(self.dept_it.head, user_new)
        self.assertTrue(user_new.is_department_head)
        # Previous head's role revoked
        self.assertFalse(self.user_it.is_department_head)
        # Exactly one user in this department holds the DEPARTMENT_HEAD role
        head_count = User.objects.filter(department=self.dept_it, roles__code=Role.Codes.DEPARTMENT_HEAD).count()
        self.assertEqual(head_count, 1)

    def test_vice_rector_responsibility_assignment_and_removal(self):
        resp = assign_vice_rector_responsibility(self.vr_acad, self.dept_it, actor=self.rector)
        self.assertTrue(resp.is_active)
        self.assertEqual(resp.vice_rector, self.vr_acad)
        self.assertEqual(resp.department, self.dept_it)

        # Scoped departments for vice rector
        scoped = self.vr_acad.get_scoped_departments()
        self.assertIn(self.dept_it, scoped)
        self.assertNotIn(self.dept_fin, scoped)

        # Removal
        remove_vice_rector_responsibility(resp, actor=self.rector)
        resp.refresh_from_db()
        self.assertFalse(resp.is_active)
        self.assertNotIn(self.dept_it, self.vr_acad.get_scoped_departments())

    def test_unique_active_responsibility_constraint(self):
        DepartmentResponsibility.objects.create(
            vice_rector=self.vr_acad,
            department=self.dept_it,
            is_active=True,
        )
        with self.assertRaises(IntegrityError):
            DepartmentResponsibility.objects.create(
                vice_rector=self.vr_acad,
                department=self.dept_it,
                is_active=True,
            )


class OrganizationViewSecurityAndAccessTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.vr_role = Role.objects.create(code=Role.Codes.VICE_RECTOR, name='Vice Rector')
        self.head_role = Role.objects.create(code=Role.Codes.DEPARTMENT_HEAD, name='Department Head')
        self.emp_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

        self.dept_it = Department.objects.create(name='IT Department', code='IT')
        self.dept_fin = Department.objects.create(name='Finance Department', code='FIN')

        self.rector = User.objects.create_user(
            username='rector', email='rector@example.com', password='Password123!', is_superuser=True,
        )
        self.rector.roles.add(self.rector_role)

        self.vr_acad = User.objects.create_user(
            username='vr.acad', email='vr.acad@example.com', password='Password123!',
        )
        self.vr_acad.roles.add(self.vr_role)
        assign_vice_rector_responsibility(self.vr_acad, self.dept_it, actor=self.rector)

        self.head_it = User.objects.create_user(
            username='head.it', email='head.it@example.com', password='Password123!', department=self.dept_it,
        )
        self.head_it.roles.add(self.head_role)
        assign_department_head(self.dept_it, self.head_it, actor=self.rector)

        self.emp_it = User.objects.create_user(
            username='emp.it', email='emp.it@example.com', password='Password123!', department=self.dept_it,
        )
        self.emp_it.roles.add(self.emp_role)

    def test_rector_can_access_all_department_views(self):
        self.client.login(username='rector', password='Password123!')
        res_list = self.client.get(reverse('department_list'))
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, 'IT Department')
        self.assertContains(res_list, 'Finance Department')

        res_detail = self.client.get(reverse('department_detail', kwargs={'pk': self.dept_it.pk}))
        self.assertEqual(res_detail.status_code, 200)

        res_create = self.client.get(reverse('department_create'))
        self.assertEqual(res_create.status_code, 200)

    def test_vice_rector_scoped_access_and_idor_protection(self):
        self.client.login(username='vr.acad', password='Password123!')

        # VR can view assigned IT department
        res_it = self.client.get(reverse('department_detail', kwargs={'pk': self.dept_it.pk}))
        self.assertEqual(res_it.status_code, 200)
        self.assertContains(res_it, 'IT Department')

        # IDOR protection: VR cannot view unassigned Finance department (403 Forbidden)
        res_fin = self.client.get(reverse('department_detail', kwargs={'pk': self.dept_fin.pk}))
        self.assertEqual(res_fin.status_code, 403)

        # VR cannot access department creation (Rector only)
        res_create = self.client.get(reverse('department_create'))
        self.assertEqual(res_create.status_code, 403)

    def test_department_head_scoped_access_and_idor_protection(self):
        self.client.login(username='head.it', password='Password123!')

        # Head can view own IT department
        res_it = self.client.get(reverse('department_detail', kwargs={'pk': self.dept_it.pk}))
        self.assertEqual(res_it.status_code, 200)

        # IDOR protection: Head cannot view Finance department
        res_fin = self.client.get(reverse('department_detail', kwargs={'pk': self.dept_fin.pk}))
        self.assertEqual(res_fin.status_code, 403)

    def test_employee_department_access_restriction(self):
        self.client.login(username='emp.it', password='Password123!')
        res_it = self.client.get(reverse('department_detail', kwargs={'pk': self.dept_it.pk}))
        self.assertEqual(res_it.status_code, 200)

        # IDOR protection: employee cannot access other department
        res_fin = self.client.get(reverse('department_detail', kwargs={'pk': self.dept_fin.pk}))
        self.assertEqual(res_fin.status_code, 403)

    def test_position_crud_rector_only(self):
        self.client.login(username='rector', password='Password123!')
        res = self.client.post(
            reverse('position_create'),
            {
                'name': 'Principal Engineer',
                'code': 'PRIN_ENG',
                'description': 'Tech lead',
                'is_active': True,
            },
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Position.objects.filter(code='PRIN_ENG').exists())

        # Non-rector blocked
        self.client.login(username='emp.it', password='Password123!')
        res_blocked = self.client.get(reverse('position_create'))
        self.assertEqual(res_blocked.status_code, 403)

    def test_responsibility_management_rector_only(self):
        self.client.login(username='rector', password='Password123!')
        res = self.client.post(
            reverse('responsibility_create'),
            {
                'vice_rector': self.vr_acad.pk,
                'department': self.dept_fin.pk,
                'start_date': '2026-08-24',
            },
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(
            DepartmentResponsibility.objects.filter(
                vice_rector=self.vr_acad, department=self.dept_fin, is_active=True
            ).exists()
        )

    def test_single_rector_rule_enforced(self):
        # Initial rector
        self.assertTrue(self.rector.is_rector)

        # Create candidate user and assign as rector
        new_rector = User.objects.create_user(
            username='new.rector', email='new.rector@example.com', password='Password123!',
        )
        assign_rector(new_rector, actor=self.rector)

        self.rector.refresh_from_db()
        new_rector.refresh_from_db()

        self.assertTrue(new_rector.is_rector)
        self.assertFalse(self.rector.is_rector)
        # Exactly one user in university holds RECTOR role
        self.assertEqual(User.objects.filter(roles__code=Role.Codes.RECTOR).count(), 1)

    def test_acting_rector_delegation_assignment_and_revocation(self):
        # VR is not acting rector initially
        self.assertFalse(self.vr_acad.is_acting_rector)
        self.assertFalse(self.vr_acad.can_act_as_rector)

        # Rector delegates to VR
        delegation = assign_acting_rector(
            rector=self.rector,
            acting_rector=self.vr_acad,
            actor=self.rector,
            reason='Annual Leave',
        )
        self.assertTrue(delegation.is_active)
        self.vr_acad.refresh_from_db()
        self.assertTrue(self.vr_acad.is_acting_rector)
        self.assertTrue(self.vr_acad.can_act_as_rector)

        # Revocation
        revoke_acting_rector(delegation, actor=self.rector)
        self.vr_acad.refresh_from_db()
        self.assertFalse(self.vr_acad.is_acting_rector)
        self.assertFalse(self.vr_acad.can_act_as_rector)

    def test_superadmin_invisible_in_structure_overview_to_staff(self):
        # Create a superadmin user
        superadmin = User.objects.create_superuser(
            username='rootadmin', email='rootadmin@example.com', password='Password123!',
        )
        # Log in as Department Head
        self.client.login(username='head.it', password='Password123!')
        res = self.client.get(reverse('organization_overview'))
        self.assertEqual(res.status_code, 200)
        # Superadmin username / email must NOT be present in page content
        self.assertNotContains(res, 'rootadmin')
        self.assertNotContains(res, 'rootadmin@example.com')

        # Log in as Employee
        self.client.login(username='emp.it', password='Password123!')
        res_emp = self.client.get(reverse('organization_overview'))
        self.assertEqual(res_emp.status_code, 200)
        self.assertNotContains(res_emp, 'rootadmin')

    def test_acting_rector_views(self):
        self.client.login(username='rector', password='Password123!')
        res_assign = self.client.post(
            reverse('acting_rector_assign'),
            {
                'acting_rector': self.vr_acad.pk,
                'start_date': '2026-09-08',
                'reason': 'Business Trip',
            },
            follow=True,
        )
        self.assertEqual(res_assign.status_code, 200)
        self.vr_acad.refresh_from_db()
        self.assertTrue(self.vr_acad.is_acting_rector)

        delegation = ActingRectorDelegation.objects.filter(acting_rector=self.vr_acad, is_active=True).first()
        self.assertIsNotNone(delegation)

        res_revoke = self.client.post(
            reverse('acting_rector_revoke', kwargs={'pk': delegation.pk}),
            follow=True,
        )
        self.assertEqual(res_revoke.status_code, 200)
        self.vr_acad.refresh_from_db()
        self.assertFalse(self.vr_acad.is_acting_rector)

