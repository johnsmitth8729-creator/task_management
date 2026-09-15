import io
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from core.models import AuditLog, Notification
from files.models import TaskFile, TaskFolder, TaskReport
from files.permissions import (
    can_delete_file,
    can_download_file,
    can_edit_report,
    can_upload_task_file,
    can_view_report,
    can_view_task_files,
)
from files.services import (
    create_task_folder,
    create_task_report,
    delete_task_folder,
    move_task_file,
    rename_task_folder,
    soft_delete_task_file,
    update_task_report,
    upload_task_file,
)
from files.validators import (
    calculate_file_checksum,
    detect_content_type,
    sanitize_filename,
    validate_file_extension,
    validate_file_size,
)
from organization.models import Department, DepartmentResponsibility
from tasks.models import Task, TaskAssignment, TaskNote, TaskSubmission


class Phase6FilesTestBase(TestCase):
    def setUp(self):
        # Roles
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.vr_role = Role.objects.create(code=Role.Codes.VICE_RECTOR, name='Vice Rector')
        self.dh_role = Role.objects.create(code=Role.Codes.DEPARTMENT_HEAD, name='Dept Head')
        self.emp_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

        # Departments
        self.dept_it = Department.objects.create(code='IT', name='Information Technology')
        self.dept_fin = Department.objects.create(code='FIN', name='Finance')
        self.dept_hr = Department.objects.create(code='HR', name='Human Resources')

        # Users
        self.superadmin = User.objects.create_superuser(
            username='superadmin', email='superadmin@test.com', password='Pass!12345'
        )
        self.rector = User.objects.create_user(
            username='test_rector', email='rector@test.com', password='Pass!12345'
        )
        self.rector.roles.set([self.rector_role])

        self.vice_rector = User.objects.create_user(
            username='test_vr', email='vr@test.com', password='Pass!12345'
        )
        self.vice_rector.roles.set([self.vr_role])
        DepartmentResponsibility.objects.create(
            vice_rector=self.vice_rector, department=self.dept_it, is_active=True
        )

        self.head_it = User.objects.create_user(
            username='head_it', email='head.it@test.com', password='Pass!12345', department=self.dept_it
        )
        self.head_it.roles.set([self.dh_role])
        self.dept_it.head = self.head_it
        self.dept_it.save()

        self.head_fin = User.objects.create_user(
            username='head_fin', email='head.fin@test.com', password='Pass!12345', department=self.dept_fin
        )
        self.head_fin.roles.set([self.dh_role])
        self.dept_fin.head = self.head_fin
        self.dept_fin.save()

        self.emp1 = User.objects.create_user(
            username='emp1_it', email='emp1@test.com', password='Pass!12345', department=self.dept_it
        )
        self.emp1.roles.set([self.emp_role])

        self.emp2_fin = User.objects.create_user(
            username='emp2_fin', email='emp2@test.com', password='Pass!12345', department=self.dept_fin
        )
        self.emp2_fin.roles.set([self.emp_role])

        # Tasks
        self.task_it = Task.objects.create(
            title='IT Portal Task',
            creator=self.rector,
            responsible_department=self.dept_it,
            status=Task.Status.IN_PROGRESS,
            deadline=timezone.now().date() + timedelta(days=10),
        )
        self.assign_it = TaskAssignment.objects.create(
            task=self.task_it,
            user=self.emp1,
            assigned_by=self.head_it,
            assignment_status=TaskAssignment.AssignmentStatus.IN_PROGRESS,
        )

        self.task_fin = Task.objects.create(
            title='Finance Task',
            creator=self.rector,
            responsible_department=self.dept_fin,
            status=Task.Status.IN_PROGRESS,
            deadline=timezone.now().date() + timedelta(days=5),
        )
        self.assign_fin = TaskAssignment.objects.create(
            task=self.task_fin,
            user=self.emp2_fin,
            assigned_by=self.head_fin,
            assignment_status=TaskAssignment.AssignmentStatus.IN_PROGRESS,
        )


class FileValidationTests(Phase6FilesTestBase):
    def test_valid_file_extensions(self):
        for name in ['report.pdf', 'doc.docx', 'sheet.xlsx', 'img.png', 'video.mp4', 'archive.zip']:
            ext = validate_file_extension(name)
            self.assertTrue(bool(ext))

    def test_disallowed_executables_rejected(self):
        for name in ['virus.exe', 'script.bat', 'shell.sh', 'hack.ps1', 'lib.dll', 'hack.exe.pdf']:
            with self.assertRaises(ValidationError):
                validate_file_extension(name)

    def test_empty_file_rejected(self):
        empty_file = SimpleUploadedFile('empty.pdf', b'', content_type='application/pdf')
        with self.assertRaises(ValidationError):
            validate_file_size(empty_file)

    def test_oversized_file_rejected(self):
        oversized = SimpleUploadedFile('big.pdf', b'x' * (55 * 1024 * 1024), content_type='application/pdf')
        with self.assertRaises(ValidationError):
            validate_file_size(oversized)

    def test_filename_sanitization(self):
        cleaned = sanitize_filename('../../etc/passwd.pdf')
        self.assertNotIn('..', cleaned)
        self.assertNotIn('/', cleaned)
        self.assertTrue(cleaned.endswith('.pdf'))

    def test_checksum_calculation(self):
        content = b'Hello Task Management Evidence'
        f = SimpleUploadedFile('test.txt', content)
        checksum = calculate_file_checksum(f)
        self.assertEqual(len(checksum), 64)


class FolderManagementTests(Phase6FilesTestBase):
    def test_create_folder_success(self):
        folder = create_task_folder(self.head_it, self.task_it, 'Development')
        self.assertEqual(folder.name, 'Development')
        self.assertEqual(folder.task, self.task_it)
        self.assertTrue(folder.is_active)

    def test_create_duplicate_folder_rejected(self):
        create_task_folder(self.head_it, self.task_it, 'Development')
        with self.assertRaises(ValidationError):
            create_task_folder(self.head_it, self.task_it, 'Development')

    def test_rename_folder_success(self):
        folder = create_task_folder(self.head_it, self.task_it, 'Old Name')
        rename_task_folder(self.head_it, folder, 'New Name')
        folder.refresh_from_db()
        self.assertEqual(folder.name, 'New Name')

    def test_delete_folder_moves_files_to_parent(self):
        parent = create_task_folder(self.head_it, self.task_it, 'Parent')
        sub = create_task_folder(self.head_it, self.task_it, 'Subfolder', parent_folder=parent)

        f = SimpleUploadedFile('spec.pdf', b'%PDF-1.4 Spec Content', content_type='application/pdf')
        task_file = upload_task_file(self.emp1, self.task_it, f, folder=sub, assignment=self.assign_it)

        delete_task_folder(self.head_it, sub)
        sub.refresh_from_db()
        task_file.refresh_from_db()

        self.assertFalse(sub.is_active)
        self.assertEqual(task_file.folder, parent)


class FileUploadAndDownloadTests(Phase6FilesTestBase):
    def test_employee_upload_work_evidence_success(self):
        f = SimpleUploadedFile('deliverable.pdf', b'%PDF-1.4 Deliverable evidence', content_type='application/pdf')
        task_file = upload_task_file(
            actor=self.emp1,
            task=self.task_it,
            file_obj=f,
            description='Final system architecture document',
            assignment=self.assign_it,
        )
        self.assertEqual(task_file.original_filename, 'deliverable.pdf')
        self.assertEqual(task_file.file_extension, 'pdf')
        self.assertEqual(task_file.category, TaskFile.Category.WORK_EVIDENCE)
        self.assertTrue(task_file.is_active)
        self.assertTrue(task_file.is_pdf)

    def test_unassigned_employee_cannot_upload(self):
        f = SimpleUploadedFile('unauth.pdf', b'%PDF-1.4 Content', content_type='application/pdf')
        with self.assertRaises(ValidationError):
            upload_task_file(
                actor=self.emp2_fin,  # Finance employee cannot upload to IT task
                task=self.task_it,
                file_obj=f,
            )

    def test_department_head_can_download_dept_files(self):
        f = SimpleUploadedFile('evidence.pdf', b'%PDF-1.4 Data', content_type='application/pdf')
        task_file = upload_task_file(self.emp1, self.task_it, f, assignment=self.assign_it)

        self.assertTrue(can_download_file(self.head_it, task_file))
        self.assertFalse(can_download_file(self.head_fin, task_file))

    def test_vice_rector_scoping_on_files(self):
        f = SimpleUploadedFile('it_file.pdf', b'%PDF-1.4 Data', content_type='application/pdf')
        it_file = upload_task_file(self.emp1, self.task_it, f, assignment=self.assign_it)

        f2 = SimpleUploadedFile('fin_file.pdf', b'%PDF-1.4 Data', content_type='application/pdf')
        fin_file = upload_task_file(self.emp2_fin, self.task_fin, f2, assignment=self.assign_fin)

        self.assertTrue(can_download_file(self.vice_rector, it_file))
        self.assertFalse(can_download_file(self.vice_rector, fin_file))

    def test_rector_can_download_all_files(self):
        f = SimpleUploadedFile('fin_file.pdf', b'%PDF-1.4 Data', content_type='application/pdf')
        fin_file = upload_task_file(self.emp2_fin, self.task_fin, f, assignment=self.assign_fin)
        self.assertTrue(can_download_file(self.rector, fin_file))

    def test_soft_delete_file(self):
        f = SimpleUploadedFile('to_del.pdf', b'%PDF-1.4 Data', content_type='application/pdf')
        task_file = upload_task_file(self.emp1, self.task_it, f, assignment=self.assign_it)

        soft_delete_task_file(self.emp1, task_file)
        task_file.refresh_from_db()

        self.assertFalse(task_file.is_active)
        self.assertFalse(can_download_file(self.emp1, task_file))

    def test_move_file_between_folders(self):
        folder_a = create_task_folder(self.head_it, self.task_it, 'Folder A')
        folder_b = create_task_folder(self.head_it, self.task_it, 'Folder B')

        f = SimpleUploadedFile('move_me.pdf', b'%PDF-1.4 Data', content_type='application/pdf')
        task_file = upload_task_file(self.emp1, self.task_it, f, folder=folder_a, assignment=self.assign_it)
        self.assertEqual(task_file.folder, folder_a)

        move_task_file(self.emp1, task_file, folder_b)
        task_file.refresh_from_db()
        self.assertEqual(task_file.folder, folder_b)


class TaskReportTests(Phase6FilesTestBase):
    def test_create_task_report_success(self):
        report = create_task_report(
            actor=self.emp1,
            task=self.task_it,
            title='Final Q3 Deliverable Report',
            summary='Completed the main development milestone.',
            completed_work='Built authentication, task engine, and file manager.',
            results='All 116 tests passing, zero regressions.',
            reporting_period='Q3 2026',
            assignment=self.assign_it,
            status=TaskReport.Status.SUBMITTED,
        )
        self.assertEqual(report.title, 'Final Q3 Deliverable Report')
        self.assertEqual(report.status, TaskReport.Status.SUBMITTED)
        self.assertEqual(report.version, 1)

    def test_update_task_report_success(self):
        report = create_task_report(
            actor=self.emp1,
            task=self.task_it,
            title='Draft Report',
            summary='Initial summary',
            completed_work='Initial work',
            results='Initial results',
            status=TaskReport.Status.DRAFT,
        )
        update_task_report(
            actor=self.emp1,
            report=report,
            title='Updated Title',
            summary='Updated Summary',
        )
        report.refresh_from_db()
        self.assertEqual(report.title, 'Updated Title')
        self.assertEqual(report.summary, 'Updated Summary')

    def test_unauthorized_user_cannot_edit_report(self):
        report = create_task_report(
            actor=self.emp1,
            task=self.task_it,
            title='Emp1 Report',
            summary='Summary',
            completed_work='Work',
            results='Results',
        )
        with self.assertRaises(ValidationError):
            update_task_report(actor=self.emp2_fin, report=report, title='Hacked Title')

    def test_export_report_pdf_docx_xlsx(self):
        report = create_task_report(
            actor=self.emp1,
            task=self.task_it,
            title='Exportable Report',
            summary='Executive summary of exported report.',
            completed_work='Detailed work breakdown.',
            results='Key results & metrics.',
            reporting_period='August 2026',
        )

        self.client.force_login(self.emp1)

        # PDF Export
        res_pdf = self.client.get(reverse('task_report_export_pdf', kwargs={'pk': report.pk}))
        self.assertEqual(res_pdf.status_code, 200)
        self.assertEqual(res_pdf['Content-Type'], 'application/pdf')
        self.assertTrue(len(res_pdf.content) > 100)

        # DOCX Export
        res_docx = self.client.get(reverse('task_report_export_docx', kwargs={'pk': report.pk}))
        self.assertEqual(res_docx.status_code, 200)
        self.assertTrue(len(res_docx.content) > 100)

        # XLSX Export
        res_xlsx = self.client.get(reverse('task_report_export_xlsx', kwargs={'pk': report.pk}))
        self.assertEqual(res_xlsx.status_code, 200)
        self.assertTrue(len(res_xlsx.content) > 100)

    def test_export_task_pdf_docx_xlsx(self):
        self.client.force_login(self.head_it)

        # Task PDF
        res_pdf = self.client.get(reverse('task_export_pdf', kwargs={'pk': self.task_it.pk}))
        self.assertEqual(res_pdf.status_code, 200)
        self.assertEqual(res_pdf['Content-Type'], 'application/pdf')

        # Task DOCX
        res_docx = self.client.get(reverse('task_export_docx', kwargs={'pk': self.task_it.pk}))
        self.assertEqual(res_docx.status_code, 200)

        # Task XLSX
        res_xlsx = self.client.get(reverse('task_export_xlsx', kwargs={'pk': self.task_it.pk}))
        self.assertEqual(res_xlsx.status_code, 200)


    def test_delete_file_post_view_success(self):
        f = SimpleUploadedFile('delete_me.pdf', b'%PDF-1.4 Data', content_type='application/pdf')
        task_file = upload_task_file(self.emp1, self.task_it, f, assignment=self.assign_it)

        self.client.force_login(self.emp1)
        res = self.client.post(reverse('task_file_delete', kwargs={'pk': task_file.pk}))
        self.assertEqual(res.status_code, 302)

        task_file.refresh_from_db()
        self.assertFalse(task_file.is_active)
        self.assertEqual(task_file.deleted_by, self.emp1)
        self.assertIsNotNone(task_file.deleted_at)

    def test_unauthorized_user_cannot_delete_file_post(self):
        f = SimpleUploadedFile('private_doc.pdf', b'%PDF-1.4 Data', content_type='application/pdf')
        task_file = upload_task_file(self.emp1, self.task_it, f, assignment=self.assign_it)

        # Finance employee attempts to delete IT file
        self.client.force_login(self.emp2_fin)
        res = self.client.post(reverse('task_file_delete', kwargs={'pk': task_file.pk}))
        self.assertEqual(res.status_code, 403)

        task_file.refresh_from_db()
        self.assertTrue(task_file.is_active)

    def test_cannot_delete_file_attached_to_approved_submission(self):
        f = SimpleUploadedFile('final_evidence.pdf', b'%PDF-1.4 Data', content_type='application/pdf')
        sub = TaskSubmission.objects.create(
            task=self.task_it,
            assignment=self.assign_it,
            submitted_by=self.emp1,
            submission_text='Final work done',
            status=TaskSubmission.SubmissionStatus.FINAL_APPROVED,
        )
        task_file = upload_task_file(self.emp1, self.task_it, f, submission=sub, assignment=self.assign_it)

        self.assertFalse(can_delete_file(self.emp1, task_file))

        self.client.force_login(self.emp1)
        res = self.client.post(reverse('task_file_delete', kwargs={'pk': task_file.pk}))
        self.assertEqual(res.status_code, 403)

        task_file.refresh_from_db()
        self.assertTrue(task_file.is_active)

    def test_folder_rename_and_delete_post_views(self):
        folder = create_task_folder(self.head_it, self.task_it, 'Original Folder')
        self.client.force_login(self.head_it)

        # Rename
        res_rename = self.client.post(
            reverse('task_folder_rename', kwargs={'pk': folder.pk}),
            {'name': 'Renamed Folder'}
        )
        self.assertEqual(res_rename.status_code, 302)
        folder.refresh_from_db()
        self.assertEqual(folder.name, 'Renamed Folder')

        # Delete
        res_delete = self.client.post(reverse('task_folder_delete', kwargs={'pk': folder.pk}))
        self.assertEqual(res_delete.status_code, 302)
        folder.refresh_from_db()
        self.assertFalse(folder.is_active)


class SecurityAndIDORTests(Phase6FilesTestBase):
    def test_unauthorized_file_download_forbidden(self):
        f = SimpleUploadedFile('private.pdf', b'%PDF-1.4 Secret', content_type='application/pdf')
        task_file = upload_task_file(self.emp1, self.task_it, f, assignment=self.assign_it)

        self.client.force_login(self.emp2_fin)
        res = self.client.get(reverse('task_file_download', kwargs={'pk': task_file.pk}))
        self.assertEqual(res.status_code, 403)

    def test_unauthorized_report_view_forbidden(self):
        report = create_task_report(
            actor=self.emp1,
            task=self.task_it,
            title='Private IT Report',
            summary='Summary',
            completed_work='Work',
            results='Results',
        )

        self.client.force_login(self.emp2_fin)
        res = self.client.get(reverse('task_report_detail', kwargs={'pk': report.pk}))
        self.assertEqual(res.status_code, 403)

    def test_django_admin_access_restricted_to_superuser_only(self):
        # Operational Rector (is_staff=False, is_superuser=False) cannot access Django admin
        self.client.force_login(self.rector)
        res_rector = self.client.get('/admin/')
        # Django admin redirects non-staff to login
        self.assertNotEqual(res_rector.status_code, 200)

        # Dedicated Superadmin (is_staff=True, is_superuser=True) CAN access Django admin
        self.client.force_login(self.superadmin)
        res_admin = self.client.get('/admin/')
        self.assertEqual(res_admin.status_code, 200)

