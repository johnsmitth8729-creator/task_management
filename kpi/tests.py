from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from core.models import AuditLog
from hr.models import EmployeeGrade, HRPermissionConfig
from kpi.calculation import (
    calculate_kpi_raw_score,
    normalize_assignment_weights,
    recalculate_employee_period_kpis,
)
from kpi.models import (
    KPIAssignment,
    KPICategory,
    KPICorrectionRequest,
    KPIDefinition,
    KPIPeriod,
    KPIResult,
    KPISnapshot,
)
from kpi.services import (
    approve_kpi_result,
    calculate_department_kpi_summary,
    calculate_kpi_period,
    calculate_university_kpi_summary,
    calculate_user_kpi_summary,
    calculate_vice_rector_kpi_summary,
    close_kpi_period,
    hr_verify_kpi_period,
    rector_approve_kpi_period,
    rector_decide_kpi_correction,
    rector_reject_kpi_period,
    rector_sign_kpi_period,
    record_kpi_result,
    request_kpi_correction,
    submit_kpi_period_for_rector,
)
from organization.models import Department, DepartmentResponsibility
from payroll.models import KPIPayrollRule, PayrollPeriod, PayrollRecord, SalaryProfile
from payroll.services import calculate_payroll
from tasks.models import Task, TaskAssignment
from tasks.services import cancel_task, final_approve_assignment


class KPI2SuiteTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Roles
        self.rector_role, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})
        self.vice_rector_role, _ = Role.objects.get_or_create(code=Role.Codes.VICE_RECTOR, defaults={'name': 'Vice Rector'})
        self.dept_head_role, _ = Role.objects.get_or_create(code=Role.Codes.DEPARTMENT_HEAD, defaults={'name': 'Department Head'})
        self.employee_role, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee'})
        self.hr_role, _ = Role.objects.get_or_create(code=Role.Codes.HR, defaults={'name': 'HR Manager'})

        # Departments
        self.it_dept = Department.objects.create(name='IT Department', code='IT_DEPT')
        self.lib_dept = Department.objects.create(name='Library', code='LIB_DEPT')

        # Users
        self.rector = User.objects.create_user(username='rector_u', email='rector@test.com', password='password123')
        self.rector.roles.add(self.rector_role)

        self.vice_rector = User.objects.create_user(username='vr_u', email='vr@test.com', password='password123')
        self.vice_rector.roles.add(self.vice_rector_role)
        DepartmentResponsibility.objects.create(vice_rector=self.vice_rector, department=self.it_dept, is_active=True)

        self.dept_head_it = User.objects.create_user(username='head_it_u', email='head_it@test.com', password='password123', department=self.it_dept)
        self.dept_head_it.roles.add(self.dept_head_role)
        self.it_dept.head = self.dept_head_it
        self.it_dept.save()

        self.hr_user = User.objects.create_user(username='hr_u', email='hr@test.com', password='password123')
        self.hr_user.roles.add(self.hr_role)
        HRPermissionConfig.objects.create(user=self.hr_user, can_manage_kpi=True, can_view_kpi=True, can_approve_kpi=True)

        self.emp1 = User.objects.create_user(username='emp1_u', email='emp1@test.com', password='password123', department=self.it_dept)
        self.emp1.roles.add(self.employee_role)

        self.emp2 = User.objects.create_user(username='emp2_u', email='emp2@test.com', password='password123', department=self.lib_dept)
        self.emp2.roles.add(self.employee_role)

        # Setup KPI Category & Definitions
        self.cat = KPICategory.objects.create(code='CORE', name='Core Performance', order=1)
        self.period = KPIPeriod.objects.create(
            code='2026-Q1-TEST',
            name='2026 Q1 Test Period',
            start_date=timezone.now().date() - timedelta(days=30),
            end_date=timezone.now().date() + timedelta(days=30),
            status=KPIPeriod.Status.OPEN,
        )

        self.kpi_max = KPIDefinition.objects.create(
            code='PAPERS_MAX',
            name='Published Papers',
            category=self.cat,
            direction=KPIDefinition.Direction.HIGHER_IS_BETTER,
            measurement_type=KPIDefinition.MeasurementType.NUMERIC,
            target_value=Decimal('4.00'),
            configured_weight=Decimal('20.00'),
        )
        self.kpi_min = KPIDefinition.objects.create(
            code='ERRORS_MIN',
            name='Defect Rate',
            category=self.cat,
            direction=KPIDefinition.Direction.LOWER_IS_BETTER,
            measurement_type=KPIDefinition.MeasurementType.NUMERIC,
            target_value=Decimal('2.00'),
            configured_weight=Decimal('20.00'),
        )
        self.kpi_exact = KPIDefinition.objects.create(
            code='HOURS_EXACT',
            name='Lecture Hours Target',
            category=self.cat,
            direction=KPIDefinition.Direction.TARGET_IS_BEST,
            measurement_type=KPIDefinition.MeasurementType.NUMERIC,
            target_value=Decimal('100.00'),
            configured_weight=Decimal('10.00'),
        )

        # Assignments for emp1 (weights: 20, 20, 10 -> total 50. Normalized should be 40%, 40%, 20%)
        self.assign_max = KPIAssignment.objects.create(
            kpi=self.kpi_max,
            user=self.emp1,
            period=self.period,
            target_value=Decimal('4.00'),
            configured_weight=Decimal('20.00'),
        )
        self.assign_min = KPIAssignment.objects.create(
            kpi=self.kpi_min,
            user=self.emp1,
            period=self.period,
            target_value=Decimal('2.00'),
            configured_weight=Decimal('20.00'),
        )
        self.assign_exact = KPIAssignment.objects.create(
            kpi=self.kpi_exact,
            user=self.emp1,
            period=self.period,
            target_value=Decimal('100.00'),
            configured_weight=Decimal('10.00'),
        )

    def test_dynamic_weight_normalization(self):
        normalized = normalize_assignment_weights(self.emp1, self.period)
        weights = {a.id: a.normalized_weight for a in normalized}
        self.assertEqual(weights[self.assign_max.id], Decimal('40.00'))
        self.assertEqual(weights[self.assign_min.id], Decimal('40.00'))
        self.assertEqual(weights[self.assign_exact.id], Decimal('20.00'))
        self.assertEqual(sum(weights.values()), Decimal('100.00'))

    def test_raw_score_calculation_directions(self):
        # 1. MAXIMIZE: actual=4 on target=4 -> 100.00; actual=2 on target=4 -> 50.00
        self.assertEqual(calculate_kpi_raw_score(self.kpi_max, Decimal('4.00'), Decimal('4.00')), Decimal('100.00'))
        self.assertEqual(calculate_kpi_raw_score(self.kpi_max, Decimal('2.00'), Decimal('4.00')), Decimal('50.00'))

        # 2. MINIMIZE: target=2. If actual=1 (less defects than 2), score = 100.00. If actual=3, score = 50.00
        self.assertEqual(calculate_kpi_raw_score(self.kpi_min, Decimal('1.00'), Decimal('2.00')), Decimal('100.00'))
        self.assertEqual(calculate_kpi_raw_score(self.kpi_min, Decimal('3.00'), Decimal('2.00')), Decimal('50.00'))

        # 3. EXACT: target=100. If actual=100 -> 100.00; if actual=90 (10% off) -> 90.00
        self.assertEqual(calculate_kpi_raw_score(self.kpi_exact, Decimal('100.00'), Decimal('100.00')), Decimal('100.00'))
        self.assertEqual(calculate_kpi_raw_score(self.kpi_exact, Decimal('90.00'), Decimal('100.00')), Decimal('90.00'))

    def test_recalculate_employee_period_kpis(self):
        # Set actual values
        record_kpi_result(self.dept_head_it, self.assign_max, Decimal('4.00'))  # raw: 100, norm weight: 40% -> 40 pts
        record_kpi_result(self.dept_head_it, self.assign_min, Decimal('2.00'))  # raw: 100, norm weight: 40% -> 40 pts
        record_kpi_result(self.dept_head_it, self.assign_exact, Decimal('100.00'))  # raw: 100, norm weight: 20% -> 20 pts

        results = recalculate_employee_period_kpis(self.emp1, self.period, actor=self.dept_head_it)
        self.assertEqual(len(results), 3)

        summary = calculate_user_kpi_summary(self.emp1, self.period)
        self.assertEqual(summary['total_score'], 100.0)

    def test_full_period_lifecycle_and_rector_rejection(self):
        # 1. Calculate Period
        calculate_kpi_period(self.hr_user, self.period)
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, KPIPeriod.Status.UNDER_REVIEW)

        # 2. HR Verifies and submits
        hr_verify_kpi_period(self.hr_user, self.period, notes='All verified.')
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, KPIPeriod.Status.HR_VERIFIED)

        submit_kpi_period_for_rector(self.hr_user, self.period)
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, KPIPeriod.Status.PENDING_RECTOR_APPROVAL)

        # 3. Non-Rector attempting review rejection should fail
        with self.assertRaises(PermissionDenied):
            rector_reject_kpi_period(self.dept_head_it, self.period, reason='No right')

        # 4. Rector rejects without reason fails validation
        with self.assertRaises(ValidationError):
            rector_reject_kpi_period(self.rector, self.period, reason='  ')

        # 5. Rector rejects with valid reason -> returns to UNDER_REVIEW
        rector_reject_kpi_period(self.rector, self.period, reason='Discrepancy in library metrics.')
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, KPIPeriod.Status.UNDER_REVIEW)
        self.assertEqual(self.period.rejection_reason, 'Discrepancy in library metrics.')

        # 6. Re-submit and approve
        submit_kpi_period_for_rector(self.hr_user, self.period)
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, KPIPeriod.Status.PENDING_RECTOR_APPROVAL)

        rector_approve_kpi_period(self.rector, self.period, notes='Now looks consistent.')
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, KPIPeriod.Status.RECTOR_APPROVED)

        # 7. Electronic Signature by Rector
        sig = rector_sign_kpi_period(self.rector, self.period)
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, KPIPeriod.Status.RECTOR_SIGNED)
        self.assertTrue(self.period.is_immutable)
        self.assertIsNotNone(sig.verification_id)

        # Check snapshot creation and tamper detection
        snapshot = KPISnapshot.objects.filter(period=self.period).first()
        self.assertIsNotNone(snapshot)
        self.assertTrue(snapshot.verify_integrity())

        # Tampering with snapshot payload causes verification failure
        snapshot.canonical_payload['tampered'] = True
        self.assertFalse(snapshot.verify_integrity())

    def test_payroll_strictly_consumes_rector_signed_kpi(self):
        # Create payroll period
        pay_period = PayrollPeriod.objects.create(
            name='2026 March',
            code='2026-03-TEST',
            start_date=self.period.start_date,
            end_date=self.period.end_date,
            status=PayrollPeriod.Status.DRAFT,
        )

        # Create SalaryProfile for emp1
        SalaryProfile.objects.create(
            user=self.emp1,
            base_salary=Decimal('5000000.00'),
            currency='UZS',
            status=SalaryProfile.Status.ACTIVE,
            effective_from=self.period.start_date,
        )

        # Create KPI Payroll bonus rule: 90-100 score -> 10% bonus
        KPIPayrollRule.objects.create(
            name='Excellence Bonus',
            min_score=Decimal('90.00'),
            max_score=Decimal('100.00'),
            bonus_type=KPIPayrollRule.BonusType.PERCENTAGE,
            bonus_value=Decimal('10.00'),
            is_active=True,
        )

        # Record perfect scores for emp1
        record_kpi_result(self.dept_head_it, self.assign_max, Decimal('4.00'))
        record_kpi_result(self.dept_head_it, self.assign_min, Decimal('2.00'))
        record_kpi_result(self.dept_head_it, self.assign_exact, Decimal('100.00'))
        recalculate_employee_period_kpis(self.emp1, self.period, actor=self.dept_head_it)

        # While KPI period is OPEN, payroll calculation must yield ZERO KPI bonus
        pay_record = calculate_payroll(self.emp1, pay_period, actor=self.hr_user)
        kpi_lines = pay_record.lines.filter(name_snapshot__startswith='KPI Bonus')
        self.assertEqual(kpi_lines.count(), 0)

        # Now advance KPI period to RECTOR_SIGNED
        self.period.status = KPIPeriod.Status.RECTOR_APPROVED
        self.period.save()
        rector_sign_kpi_period(self.rector, self.period)

        # Calculate payroll again -> now KPI bonus line must exist!
        pay_record_signed = calculate_payroll(self.emp1, pay_period, actor=self.hr_user)
        kpi_lines_signed = pay_record_signed.lines.filter(name_snapshot__startswith='KPI Bonus')
        self.assertEqual(kpi_lines_signed.count(), 1)
        self.assertGreater(kpi_lines_signed.first().amount, Decimal('0.00'))

    def test_correction_request_workflow(self):
        res = record_kpi_result(self.dept_head_it, self.assign_max, Decimal('2.00'))
        # Emp1 contests the score with evidence
        req = request_kpi_correction(
            requester=self.emp1,
            result=res,
            requested_actual_value=Decimal('4.00'),
            reason='Two papers were published in indexed journal on the 28th.',
            evidence='DOI: 10.1000/182',
        )
        self.assertEqual(req.status, KPICorrectionRequest.Status.REQUESTED)

        # Rector approves the correction
        rector_decide_kpi_correction(self.rector, req, approved=True, decision_reason='Verified DOI index.')
        req.refresh_from_db()
        self.assertEqual(req.status, KPICorrectionRequest.Status.APPROVED)

        # Result is updated and raw score recalculated to 100.00
        res.refresh_from_db()
        self.assertEqual(res.actual_value, Decimal('4.00'))
        self.assertEqual(res.raw_score, Decimal('100.00'))

    def test_role_scoped_kpi_views(self):
        # Employee sees personal dashboard
        self.client.login(username='emp1_u', password='password123')
        resp = self.client.get(reverse('kpi:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['view_type'], 'EMPLOYEE')

        # Department Head sees department dashboard
        self.client.login(username='head_it_u', password='password123')
        resp = self.client.get(reverse('kpi:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['view_type'], 'DEPARTMENT')

        # Vice Rector sees supervised sector dashboard
        self.client.login(username='vr_u', password='password123')
        resp = self.client.get(reverse('kpi:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['view_type'], 'VICE_RECTOR')

        # Rector sees university-wide dashboard
        self.client.login(username='rector_u', password='password123')
        resp = self.client.get(reverse('kpi:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['view_type'], 'UNIVERSITY')

    def test_kpi_evaluation_authorization_and_idor(self):
        # Dept Head of IT can evaluate Employee 1
        self.client.login(username='head_it_u', password='password123')
        resp = self.client.get(reverse('kpi:evaluate', kwargs={'pk': self.assign_max.pk}))
        self.assertEqual(resp.status_code, 200)

        # Employee 2 (from Library) trying to evaluate Employee 1 assignment -> 403
        self.client.login(username='emp2_u', password='password123')
        resp = self.client.get(reverse('kpi:evaluate', kwargs={'pk': self.assign_max.pk}))
        self.assertEqual(resp.status_code, 403)
