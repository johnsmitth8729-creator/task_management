from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.models import Role
from organization.models import Department, Position


class Command(BaseCommand):
    help = 'Create development-only seed data for Phase 1.'

    def handle(self, *args, **options):
        roles = {
            Role.Codes.RECTOR: 'Rector / Superadmin',
            Role.Codes.VICE_RECTOR: 'Vice Rector / Admin',
            Role.Codes.DEPARTMENT_HEAD: 'Department Head',
            Role.Codes.EMPLOYEE: 'Employee / User',
        }
        role_objects = {}
        for code, name in roles.items():
            role_objects[code], _ = Role.objects.update_or_create(
                code=code,
                defaults={'name': name, 'is_active': True},
            )

        departments = {
            'IT': 'Information Technology',
            'LIB': 'Library',
        }
        department_objects = {}
        for code, name in departments.items():
            department_objects[code], _ = Department.objects.update_or_create(
                code=code,
                defaults={'name': name, 'is_active': True},
            )

        positions = {
            'RECTOR': 'Rector',
            'VICE_RECTOR': 'Vice Rector',
            'DEPT_HEAD': 'Department Head',
            'DEVELOPER': 'Developer',
            'LIBRARIAN': 'Librarian',
        }
        position_objects = {}
        for code, name in positions.items():
            position_objects[code], _ = Position.objects.update_or_create(
                code=code,
                defaults={'name': name, 'is_active': True},
            )

        User = get_user_model()
        demo_password = 'ChangeMe12345!'
        users = [
            {
                'username': 'rector',
                'email': 'rector@example.test',
                'first_name': 'Development',
                'last_name': 'Rector',
                'role': Role.Codes.RECTOR,
                'department': None,
                'position': position_objects['RECTOR'],
                'is_staff': True,
                'is_superuser': True,
            },
            {
                'username': 'vice.rector',
                'email': 'vice.rector@example.test',
                'first_name': 'Development',
                'last_name': 'Vice Rector',
                'role': Role.Codes.VICE_RECTOR,
                'department': department_objects['IT'],
                'position': position_objects['VICE_RECTOR'],
                'is_staff': True,
                'is_superuser': False,
            },
            {
                'username': 'department.head',
                'email': 'department.head@example.test',
                'first_name': 'Development',
                'last_name': 'Head',
                'role': Role.Codes.DEPARTMENT_HEAD,
                'department': department_objects['IT'],
                'position': position_objects['DEPT_HEAD'],
                'is_staff': True,
                'is_superuser': False,
            },
            {
                'username': 'employee.one',
                'email': 'employee.one@example.test',
                'first_name': 'Development',
                'last_name': 'Employee One',
                'role': Role.Codes.EMPLOYEE,
                'department': department_objects['IT'],
                'position': position_objects['DEVELOPER'],
                'is_staff': False,
                'is_superuser': False,
            },
            {
                'username': 'employee.two',
                'email': 'employee.two@example.test',
                'first_name': 'Development',
                'last_name': 'Employee Two',
                'role': Role.Codes.EMPLOYEE,
                'department': department_objects['LIB'],
                'position': position_objects['LIBRARIAN'],
                'is_staff': False,
                'is_superuser': False,
            },
        ]

        for data in users:
            role = role_objects[data.pop('role')]
            user, created = User.objects.update_or_create(
                username=data['username'],
                defaults=data,
            )
            if created:
                user.set_password(demo_password)
                user.save(update_fields=['password'])
            user.roles.set([role])

        self.stdout.write(self.style.SUCCESS('Development seed data created.'))
        self.stdout.write('Development-only password for seeded users: ChangeMe12345!')
