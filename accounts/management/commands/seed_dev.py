from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Role
from organization.models import Department, DepartmentResponsibility, Position
from organization.services import assign_department_head, assign_vice_rector_responsibility


class Command(BaseCommand):
    help = 'Create development-only seed data for Phase 2.'

    def handle(self, *args, **options):
        # 1. ROLES
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
            'RECTOR': {'name': 'Rector of University', 'dept': None},
            'VICE_RECTOR_ACAD': {'name': 'Vice Rector for Academic Affairs', 'dept': None},
            'VICE_RECTOR_FIN': {'name': 'Vice Rector for Finance & Operations', 'dept': None},
            'DEPT_HEAD': {'name': 'Head of Department', 'dept': None},
            'SNR_DEV': {'name': 'Senior Software Engineer', 'dept': department_objects['IT']},
            'DEVELOPER': {'name': 'Software Developer', 'dept': department_objects['IT']},
            'CHIEF_LIB': {'name': 'Chief Librarian', 'dept': department_objects['LIB']},
            'LIBRARIAN': {'name': 'Librarian', 'dept': department_objects['LIB']},
            'SNR_ACC': {'name': 'Senior Accountant', 'dept': department_objects['FIN']},
            'HR_OFFICER': {'name': 'HR Specialist', 'dept': department_objects['HR']},
            'ACAD_SPEC': {'name': 'Academic Coordinator', 'dept': department_objects['ACAD']},
        }
        position_objects = {}
        for code, data in positions.items():
            position_objects[code], _ = Position.objects.update_or_create(
                code=code,
                defaults={
                    'name': data['name'],
                    'department': data['dept'],
                    'is_active': True,
                },
            )

        User = get_user_model()
        demo_password = 'ChangeMe12345!'

        # 4. USERS
        users_data = [
            # Rector
            {
                'username': 'rector',
                'email': 'rector@example.test',
                'first_name': 'Akbar',
                'last_name': 'Rahmatov',
                'role': Role.Codes.RECTOR,
                'department': None,
                'position': position_objects['RECTOR'],
                'is_staff': True,
                'is_superuser': True,
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
                'is_staff': True,
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
                'is_staff': True,
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
                'is_staff': True,
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
                'is_staff': True,
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
                'is_staff': True,
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
                'is_staff': False,
                'is_superuser': False,
            },
        ]

        created_users = {}
        for data in users_data:
            role_code = data.pop('role')
            role = role_objects[role_code]
            username = data['username']
            user, created = User.objects.update_or_create(
                username=username,
                defaults=data,
            )
            if created or not user.check_password(demo_password):
                user.set_password(demo_password)
                user.save(update_fields=['password'])
            user.roles.set([role])
            created_users[username] = user

        # 5. ASSIGN DEPARTMENT HEADS
        assign_department_head(department_objects['IT'], created_users['department.head'], actor=created_users['rector'])
        assign_department_head(department_objects['LIB'], created_users['head.library'], actor=created_users['rector'])
        assign_department_head(department_objects['FIN'], created_users['head.finance'], actor=created_users['rector'])

        # 6. ASSIGN VICE RECTOR RESPONSIBILITIES
        # Vice Rector Academic -> IT + Library
        vr_acad = created_users['vice.rector']
        assign_vice_rector_responsibility(vr_acad, department_objects['IT'], actor=created_users['rector'])
        assign_vice_rector_responsibility(vr_acad, department_objects['LIB'], actor=created_users['rector'])

        # Vice Rector Finance -> Finance + HR
        vr_fin = created_users['vice.rector.finance']
        assign_vice_rector_responsibility(vr_fin, department_objects['FIN'], actor=created_users['rector'])
        assign_vice_rector_responsibility(vr_fin, department_objects['HR'], actor=created_users['rector'])

        self.stdout.write(self.style.SUCCESS('Phase 2 development seed data populated successfully.'))
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
