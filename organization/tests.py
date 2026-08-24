import uuid
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from organization.models import Department, Position

User = get_user_model()


class OrganizationModelTests(TestCase):
    def test_department_creation_and_attributes(self):
        dept = Department.objects.create(
            name='Academic Affairs',
            code='ACAD',
            description='Manages university academic programs and schedules',
        )
        self.assertIsInstance(dept.id, uuid.UUID)
        self.assertEqual(dept.name, 'Academic Affairs')
        self.assertEqual(dept.code, 'ACAD')
        self.assertEqual(str(dept), 'Academic Affairs')
        self.assertTrue(dept.is_active)
        self.assertIsNotNone(dept.created_at)
        self.assertIsNotNone(dept.updated_at)

    def test_department_code_unique_constraint(self):
        Department.objects.create(name='Dept One', code='UNIQUE_DEPT')
        with self.assertRaises(IntegrityError):
            Department.objects.create(name='Dept Two', code='UNIQUE_DEPT')

    def test_position_creation_and_attributes(self):
        pos = Position.objects.create(
            name='Senior Lecturer',
            code='SNR_LECTURER',
            description='Senior academic teaching position',
        )
        self.assertIsInstance(pos.id, uuid.UUID)
        self.assertEqual(pos.name, 'Senior Lecturer')
        self.assertEqual(pos.code, 'SNR_LECTURER')
        self.assertEqual(str(pos), 'Senior Lecturer')
        self.assertTrue(pos.is_active)
        self.assertIsNotNone(pos.created_at)
        self.assertIsNotNone(pos.updated_at)

    def test_position_code_unique_constraint(self):
        Position.objects.create(name='Pos One', code='UNIQUE_POS')
        with self.assertRaises(IntegrityError):
            Position.objects.create(name='Pos Two', code='UNIQUE_POS')

    def test_user_department_and_position_association(self):
        dept = Department.objects.create(name='Finance', code='FIN')
        pos = Position.objects.create(name='Accountant', code='ACC')
        user = User.objects.create_user(
            username='finuser',
            email='fin@example.com',
            password='Password123!',
            department=dept,
            position=pos,
        )
        self.assertEqual(user.department, dept)
        self.assertEqual(user.position, pos)
        self.assertIn(user, dept.users.all())
        self.assertIn(user, pos.users.all())
