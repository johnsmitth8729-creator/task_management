from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

# --------------------------------------------------------------------------
# Python 3.14 + Django 6.1 compatibility patch:
# Django's template Context.__copy__ calls super().__copy__() which fails in
# Python 3.14 because the new super() no longer sets __dict__ on objects that
# don't have one. Patch it so tests can copy template contexts without crashing.
# --------------------------------------------------------------------------
try:
    from django.template.context import BaseContext

    def _patched_copy(self):
        duplicate = self.__class__.__new__(self.__class__)
        duplicate.__dict__.update(self.__dict__)
        duplicate.dicts = self.dicts[:]
        return duplicate

    if not getattr(BaseContext, '_py314_patched', False):
        BaseContext.__copy__ = _patched_copy
        BaseContext._py314_patched = True
except Exception:
    pass
# --------------------------------------------------------------------------

from accounts.models import Role, User
from hr.models import EmployeeGrade, HRPermissionConfig
from kpi.models import KPIAssignment, KPICategory, KPIDefinition, KPIPeriod, KPIResult
from organization.models import Department, DepartmentResponsibility, Position
from payroll.exports import generate_payslip_pdf, generate_period_payroll_excel
from payroll.models import (
    CompensationComponent,
    KPIPayrollRule,
    PayrollAdjustment,
    PayrollLine,
    PayrollPeriod,
    PayrollRecord,
    PayrollTaxRule,
    SalaryBand,
    SalaryHistory,
    SalaryProfile,
)
from payroll.services import (
    approve_period_payroll,
    approve_payroll_record,
    calculate_period_payroll,
    calculate_payroll,
    close_payroll_period,
    create_salary_profile,
    mark_payroll_paid,
    quantize_money,
)


class PayrollModelAndCalculationTests(TestCase):
    def setUp(self):
        # Roles
        self.rector_role, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})
        self.dh_role, _ = Role.objects.get_or_create(code=Role.Codes.DEPARTMENT_HEAD, defaults={'name': 'Dept Head'})
        self.emp_role, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee'})

        # Departments & Positions
        self.dept_it = Department.objects.create(name="IT Services", code="IT")
        self.dept_fin = Department.objects.create(name="Finance", code="FIN")
        self.pos_dev = Position.objects.create(name="Senior Developer", department=self.dept_it, code="POS_DEV")
        self.pos_acc = Position.objects.create(name="Accountant", department=self.dept_fin, code="POS_ACC")

        # Grades
        self.grade_g3 = EmployeeGrade.objects.create(name="Grade 3 Professional", code="G3", rank=3)
        self.grade_g4 = EmployeeGrade.objects.create(name="Grade 4 Senior", code="G4", rank=4)

        # Users
        self.superadmin = User.objects.create_superuser(
            username="test.superadmin",
            email="superadmin@example.test",
            password="Password123!",
        )
        self.rector = User.objects.create_user(
            username="test.rector",
            email="rector@example.test",
            password="Password123!",
        )
        self.rector.roles.add(self.rector_role)

        self.dev_user = User.objects.create_user(
            username="test.dev",
            email="dev@example.test",
            password="Password123!",
            first_name="Aziz",
            last_name="Sobirov",
            department=self.dept_it,
            position=self.pos_dev,
            grade=self.grade_g3,
        )
        self.dev_user.roles.add(self.emp_role)

        self.fin_user = User.objects.create_user(
            username="test.fin",
            email="fin@example.test",
            password="Password123!",
            department=self.dept_fin,
            position=self.pos_acc,
            grade=self.grade_g3,
        )
        self.fin_user.roles.add(self.emp_role)

        # Period
        self.period = PayrollPeriod.objects.create(
            name="October 2026",
            code="2026-10",
            period_type=PayrollPeriod.PeriodType.MONTHLY,
            start_date=timezone.datetime(2026, 10, 1).date(),
            end_date=timezone.datetime(2026, 10, 31).date(),
            status=PayrollPeriod.Status.OPEN,
            created_by=self.rector,
        )

    def test_quantize_money_round_half_up(self):
        val = quantize_money(Decimal("100.555"))
        self.assertEqual(val, Decimal("100.56"))
        val2 = quantize_money(Decimal("100.554"))
        self.assertEqual(val2, Decimal("100.55"))

    def test_salary_profile_creation_and_history_audit(self):
        # Create initial salary
        p1 = create_salary_profile(
            actor=self.rector,
            user=self.dev_user,
            base_salary=Decimal("10000000.00"),
            notes="Initial salary profile",
        )
        self.assertTrue(p1.is_active)
        self.assertEqual(p1.status, SalaryProfile.Status.ACTIVE)
        self.assertEqual(p1.base_salary, Decimal("10000000.00"))

        # Create updated salary
        p2 = create_salary_profile(
            actor=self.rector,
            user=self.dev_user,
            base_salary=Decimal("12500000.00"),
            notes="Annual Merit Promotion",
        )
        p1.refresh_from_db()
        self.assertFalse(p1.is_active)
        self.assertEqual(p1.status, SalaryProfile.Status.INACTIVE)
        self.assertTrue(p2.is_active)
        self.assertEqual(p2.status, SalaryProfile.Status.ACTIVE)

        # Check salary history
        histories = SalaryHistory.objects.filter(user=self.dev_user)
        self.assertEqual(histories.count(), 2)
        initial_history = histories.filter(previous_salary__isnull=True).first()
        self.assertIsNotNone(initial_history)
        self.assertEqual(initial_history.new_salary, Decimal("10000000.00"))

        update_history = histories.filter(previous_salary=Decimal("10000000.00")).first()
        self.assertIsNotNone(update_history)
        self.assertEqual(update_history.new_salary, Decimal("12500000.00"))
        self.assertEqual(update_history.changed_by, self.rector)

    def test_full_payroll_calculation_engine_with_components_and_tax(self):
        # Set base salary: 10,000,000 UZS
        create_salary_profile(
            actor=self.rector,
            user=self.dev_user,
            base_salary=Decimal("10000000.00"),
        )

        # Fixed Allowance: Transport (non-taxable) = 500,000 UZS
        CompensationComponent.objects.create(
            name="Transport Allowance",
            code="TEST_TRANS",
            component_type=CompensationComponent.ComponentType.ALLOWANCE,
            calculation_type=CompensationComponent.CalculationType.FIXED,
            default_value=Decimal("500000.00"),
            is_taxable=False,
            is_active=True,
        )

        # Percentage Bonus: Responsibility (taxable) = 10% of base = 1,000,000 UZS
        CompensationComponent.objects.create(
            name="Responsibility Bonus",
            code="TEST_BONUS",
            component_type=CompensationComponent.ComponentType.BONUS,
            calculation_type=CompensationComponent.CalculationType.PERCENTAGE,
            default_value=Decimal("10.00"),
            is_taxable=True,
            is_active=True,
        )

        # Deduction: Union (1% of base) = 100,000 UZS
        CompensationComponent.objects.create(
            name="Union Dues",
            code="TEST_UNION",
            component_type=CompensationComponent.ComponentType.DEDUCTION,
            calculation_type=CompensationComponent.CalculationType.PERCENTAGE,
            default_value=Decimal("1.00"),
            is_taxable=False,
            is_active=True,
        )

        # Tax Rule: 12% on Taxable Gross
        PayrollTaxRule.objects.create(
            name="PIT 12%",
            code="TEST_PIT_12",
            percentage=Decimal("12.00"),
            applies_to=PayrollTaxRule.AppliesTo.TAXABLE_GROSS,
            is_active=True,
        )

        # Calculate payroll
        record = calculate_payroll(self.dev_user, self.period, actor=self.rector)

        # Base: 10,000,000
        # Allowances: 500,000
        # Bonuses: 1,000,000
        # KPI Bonus: 0.00
        # Gross = 10,000,000 + 500,000 + 1,000,000 = 11,500,000
        self.assertEqual(record.gross_salary, Decimal("11500000.00"))

        # Taxable Gross = Base (10,000,000) + Taxable Bonus (1,000,000) = 11,000,000
        # Tax = 12% of 11,000,000 = 1,320,000
        self.assertEqual(record.taxable_gross, Decimal("11000000.00"))
        self.assertEqual(record.tax_total, Decimal("1320000.00"))

        # Deductions = 100,000
        self.assertEqual(record.total_deductions, Decimal("100000.00"))

        # Net Salary = Gross (11,500,000) - Deductions (100,000) - Tax (1,320,000) = 10,080,000.00
        self.assertEqual(record.net_salary, Decimal("10080000.00"))

    def test_kpi_bonus_integration_with_approved_and_draft_results(self):
        create_salary_profile(
            actor=self.rector,
            user=self.dev_user,
            base_salary=Decimal("10000000.00"),
        )

        # KPI Payroll Rule: Score 90-100% gives 15% bonus of base salary
        KPIPayrollRule.objects.create(
            name="Tier 1 KPI Bonus",
            min_score=Decimal("90.00"),
            max_score=Decimal("100.00"),
            bonus_type=KPIPayrollRule.BonusType.PERCENTAGE,
            bonus_value=Decimal("15.00"),
            is_active=True,
        )

        # KPI Category and Period
        kpi_cat = KPICategory.objects.create(name="Engineering Excellence", code="ENG-EXC")
        kpi_period = KPIPeriod.objects.create(
            name="2026-Q3",
            code="2026-Q3",
            start_date=timezone.datetime(2026, 7, 1).date(),
            end_date=timezone.datetime(2026, 9, 30).date(),
            status=KPIPeriod.Status.OPEN,
        )
        kpi_def = KPIDefinition.objects.create(
            name="Task Velocity",
            code="TASK-VEL",
            category=kpi_cat,
            target_value=Decimal("100.00"),
            is_active=True,
        )

        assignment = KPIAssignment.objects.create(
            kpi=kpi_def,
            user=self.dev_user,
            period=kpi_period,
            target_value=Decimal("100.00"),
            weight=Decimal("100.00"),
            assigned_by=self.rector,
        )

        # 1. Draft/Submitted KPI result does NOT produce bonus
        res_draft = KPIResult.objects.create(
            assignment=assignment,
            actual_value=Decimal("95.00"),
            raw_score=Decimal("95.00"),
            weighted_score=Decimal("95.00"),
            status=KPIResult.Status.SUBMITTED,
        )

        record1 = calculate_payroll(self.dev_user, self.period, actor=self.rector)
        self.assertEqual(record1.kpi_bonus, Decimal("0.00"))

        # 2. Approved KPI result produces bonus when period is RECTOR_SIGNED!
        kpi_period.status = KPIPeriod.Status.RECTOR_SIGNED
        kpi_period.save()
        res_draft.status = KPIResult.Status.APPROVED
        res_draft.save()

        record2 = calculate_payroll(self.dev_user, self.period, actor=self.rector)
        # 15% of 10,000,000 = 1,500,000.00
        self.assertEqual(record2.kpi_bonus, Decimal("1500000.00"))
        self.assertEqual(record2.kpi_score_snapshot, Decimal("95.00"))

    def test_historical_snapshot_immutability_after_approval(self):
        create_salary_profile(
            actor=self.rector,
            user=self.dev_user,
            base_salary=Decimal("10000000.00"),
        )
        record = calculate_payroll(self.dev_user, self.period, actor=self.rector)

        # Snapshot checks
        self.assertEqual(record.employee_name_snapshot, self.dev_user.display_name)
        self.assertEqual(record.department_snapshot, "IT Services")
        self.assertEqual(record.position_snapshot, "Senior Developer")

        # Approve record
        approve_payroll_record(self.rector, record)
        self.assertEqual(record.status, PayrollRecord.Status.APPROVED)

        # Now mutate the user in HR
        new_dept = Department.objects.create(name="Strategic Planning", code="STRAT")
        self.dev_user.department = new_dept
        self.dev_user.first_name = "Alisher"
        self.dev_user.save()

        # Check that approved PayrollRecord snapshot did NOT change!
        record.refresh_from_db()
        self.assertEqual(record.department_snapshot, "IT Services")
        self.assertEqual(record.employee_name_snapshot, "Aziz Sobirov")


class PayrollWorkflowAndDisbursementTests(TestCase):
    def setUp(self):
        self.rector_role, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})
        self.emp_role, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee'})

        self.dept = Department.objects.create(name="IT", code="IT")
        self.rector = User.objects.create_user(
            username="rector",
            email="rector@example.test",
            password="Password123!",
        )
        self.rector.roles.add(self.rector_role)

        self.emp = User.objects.create_user(
            username="emp1",
            email="emp1@example.test",
            password="Password123!",
            department=self.dept,
        )
        self.emp.roles.add(self.emp_role)

        self.period = PayrollPeriod.objects.create(
            name="November 2026",
            code="2026-11",
            period_type=PayrollPeriod.PeriodType.MONTHLY,
            start_date=timezone.datetime(2026, 11, 1).date(),
            end_date=timezone.datetime(2026, 11, 30).date(),
            status=PayrollPeriod.Status.OPEN,
            created_by=self.rector,
        )
        create_salary_profile(
            actor=self.rector,
            user=self.emp,
            base_salary=Decimal("8000000.00"),
        )

    def test_period_lifecycle_calculate_approve_close(self):
        # 1. Calculate
        calculate_period_payroll(self.period, actor=self.rector)
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, PayrollPeriod.Status.PENDING_APPROVAL)
        self.assertEqual(self.period.records.count(), 1)

        record = self.period.records.first()
        self.assertEqual(record.status, PayrollRecord.Status.CALCULATED)

        # 2. Approve Period
        approve_period_payroll(self.rector, self.period)
        self.period.refresh_from_db()
        record.refresh_from_db()
        self.assertEqual(self.period.status, PayrollPeriod.Status.APPROVED)
        self.assertEqual(record.status, PayrollRecord.Status.APPROVED)

        # 3. Mark Paid
        mark_payroll_paid(self.rector, record, payment_reference="REF-TEST-999")
        record.refresh_from_db()
        self.assertEqual(record.payment_status, PayrollRecord.PaymentStatus.PAID)
        self.assertEqual(record.payment_reference, "REF-TEST-999")
        self.assertIsNotNone(record.paid_at)

        # 4. Close Period
        close_payroll_period(self.rector, self.period)
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, PayrollPeriod.Status.CLOSED)

        # 5. Attempting to calculate a closed period must fail with ValidationError
        with self.assertRaises(ValidationError):
            calculate_period_payroll(self.period, actor=self.rector)


class PayrollSecurityAndIDORTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.rector_role, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})
        self.dh_role, _ = Role.objects.get_or_create(code=Role.Codes.DEPARTMENT_HEAD, defaults={'name': 'Dept Head'})
        self.hr_role, _ = Role.objects.get_or_create(code=Role.Codes.HR, defaults={'name': 'HR Manager'})
        self.emp_role, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee'})

        self.dept_it = Department.objects.create(name="IT", code="IT")
        self.dept_lib = Department.objects.create(name="Library", code="LIB")

        self.superadmin = User.objects.create_superuser(
            username="sec.superadmin",
            email="sec.superadmin@example.test",
            password="Password123!",
        )
        self.rector = User.objects.create_user(
            username="sec.rector",
            email="sec.rector@example.test",
            password="Password123!",
        )
        self.rector.roles.add(self.rector_role)

        self.head_it = User.objects.create_user(
            username="sec.head_it",
            email="head_it@example.test",
            password="Password123!",
            department=self.dept_it,
        )
        self.head_it.roles.add(self.dh_role)
        self.dept_it.head = self.head_it
        self.dept_it.save()

        self.hr_mgr = User.objects.create_user(
            username="sec.hr_mgr",
            email="hr_mgr@example.test",
            password="Password123!",
        )
        self.hr_mgr.roles.add(self.hr_role)

        # Configure HR permissions
        HRPermissionConfig.objects.create(
            user=self.hr_mgr,
            can_view_payroll=True,
            can_manage_salary=True,
            can_create_adjustment=True,
            can_manage_payroll=False,  # cannot calculate/close periods
            can_approve_payroll=False,  # cannot approve payroll
            can_mark_paid=True,
            can_view_payroll_reports=True,
        )

        self.emp1 = User.objects.create_user(
            username="sec.emp1",
            email="emp1@example.test",
            password="Password123!",
            department=self.dept_it,
        )
        self.emp1.roles.add(self.emp_role)

        self.emp2 = User.objects.create_user(
            username="sec.emp2",
            email="emp2@example.test",
            password="Password123!",
            department=self.dept_lib,
        )
        self.emp2.roles.add(self.emp_role)

        self.period = PayrollPeriod.objects.create(
            name="December 2026",
            code="2026-12",
            period_type=PayrollPeriod.PeriodType.MONTHLY,
            start_date=timezone.datetime(2026, 12, 1).date(),
            end_date=timezone.datetime(2026, 12, 31).date(),
            status=PayrollPeriod.Status.OPEN,
            created_by=self.rector,
        )

        create_salary_profile(actor=self.rector, user=self.emp1, base_salary=Decimal("7000000.00"))
        create_salary_profile(actor=self.rector, user=self.emp2, base_salary=Decimal("6000000.00"))

        self.rec1 = calculate_payroll(self.emp1, self.period, actor=self.rector)
        self.rec2 = calculate_payroll(self.emp2, self.period, actor=self.rector)

        approve_payroll_record(self.rector, self.rec1)
        approve_payroll_record(self.rector, self.rec2)

    def test_employee_cannot_view_other_employee_payslip_idor(self):
        # Log in as emp1
        self.client.force_login(self.emp1)

        # emp1 accessing own payslip -> 200 OK
        resp_own = self.client.get(reverse("payroll:my_payslip_detail", kwargs={"pk": self.rec1.pk}))
        self.assertEqual(resp_own.status_code, 200)

        # emp1 attempting to access emp2's payslip -> 403 Forbidden
        resp_other = self.client.get(reverse("payroll:my_payslip_detail", kwargs={"pk": self.rec2.pk}))
        self.assertEqual(resp_other.status_code, 403)

        # emp1 attempting to access general payroll record detail -> 403 Forbidden
        resp_general = self.client.get(reverse("payroll:record_detail", kwargs={"pk": self.rec2.pk}))
        self.assertEqual(resp_general.status_code, 403)

    def test_department_head_cannot_edit_salary(self):
        # Department head cannot access salary create/edit URL
        self.client.force_login(self.head_it)
        resp = self.client.get(reverse("payroll:salary_create", kwargs={"user_id": self.emp1.pk}))
        self.assertEqual(resp.status_code, 403)

    def test_department_head_cannot_view_other_department_record(self):
        # head_it (IT) cannot view emp2 (Library) record
        self.client.force_login(self.head_it)
        resp = self.client.get(reverse("payroll:record_detail", kwargs={"pk": self.rec2.pk}))
        self.assertEqual(resp.status_code, 403)

        # Per Phase 8 privacy rules: Dept Head CANNOT view any individual record,
        # even within their own department.
        resp_own_dept = self.client.get(reverse("payroll:record_detail", kwargs={"pk": self.rec1.pk}))
        self.assertEqual(resp_own_dept.status_code, 403)

    def test_hr_permission_boundaries(self):
        self.client.force_login(self.hr_mgr)

        # hr_mgr has can_manage_salary=True -> can access salary adjust
        resp_sal = self.client.get(reverse("payroll:salary_create", kwargs={"user_id": self.emp1.pk}))
        self.assertEqual(resp_sal.status_code, 200)

        # hr_mgr has can_approve_payroll=False -> POST to approve record returns 403
        resp_appr = self.client.post(reverse("payroll:record_approve", kwargs={"pk": self.rec1.pk}))
        self.assertEqual(resp_appr.status_code, 403)


class PayrollExportTests(TestCase):
    def setUp(self):
        self.rector_role, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})
        self.emp_role, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee'})

        self.dept = Department.objects.create(name="IT", code="IT")
        self.rector = User.objects.create_user(
            username="exp.rector",
            email="rector@example.test",
            password="Password123!",
        )
        self.rector.roles.add(self.rector_role)

        self.emp = User.objects.create_user(
            username="exp.emp",
            email="emp@example.test",
            password="Password123!",
            department=self.dept,
        )
        self.emp.roles.add(self.emp_role)

        self.period = PayrollPeriod.objects.create(
            name="Export Period",
            code="2026-EXP",
            period_type=PayrollPeriod.PeriodType.MONTHLY,
            start_date=timezone.datetime(2026, 10, 1).date(),
            end_date=timezone.datetime(2026, 10, 31).date(),
            status=PayrollPeriod.Status.OPEN,
            created_by=self.rector,
        )
        create_salary_profile(actor=self.rector, user=self.emp, base_salary=Decimal("9000000.00"))
        self.record = calculate_payroll(self.emp, self.period, actor=self.rector)
        approve_payroll_record(self.rector, self.record)

    def test_generate_payslip_pdf_format(self):
        pdf_bytes = generate_payslip_pdf(self.record)
        self.assertTrue(isinstance(pdf_bytes, bytes))
        self.assertTrue(len(pdf_bytes) > 0)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_generate_period_payroll_excel_format(self):
        excel_bytes = generate_period_payroll_excel(self.period)
        self.assertTrue(isinstance(excel_bytes, bytes))
        self.assertTrue(len(excel_bytes) > 0)
        # Check ZIP / XLSX magic bytes (PK\x03\x04)
        self.assertTrue(excel_bytes.startswith(b"PK\x03\x04"))


# =============================================================================
# Phase 8 — RBAC, Privacy & IDOR Prevention Tests
# =============================================================================

from payroll.models import PayrollPermissionConfig
from payroll.permissions import (
    can_view_user_salary,
    can_view_payroll_record,
    can_manage_salary,
    can_approve_payroll,
    can_mark_paid,
    can_create_adjustment,
    can_view_payroll_reports,
    get_payroll_permission,
)


class RBACPayrollPrivacyTests(TestCase):
    """
    Tests for Phase 8 salary privacy rules:
    - Individual salary is confidential (visible only to self, Finance, HR, Superadmin).
    - Rector, Vice Rector, Department Head: aggregate only; CANNOT view individual salaries.
    - Finance role: full operational payroll access; cannot do HR governance.
    - IDOR prevention: cross-employee payslip/PDF/Excel URL access returns 403.
    """

    def setUp(self):
        # Roles
        self.rector_role, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})
        self.vr_role, _ = Role.objects.get_or_create(code=Role.Codes.VICE_RECTOR, defaults={'name': 'Vice Rector'})
        self.dh_role, _ = Role.objects.get_or_create(code=Role.Codes.DEPARTMENT_HEAD, defaults={'name': 'Dept Head'})
        self.hr_role, _ = Role.objects.get_or_create(code=Role.Codes.HR, defaults={'name': 'HR Manager'})
        self.finance_role, _ = Role.objects.get_or_create(code=Role.Codes.FINANCE, defaults={'name': 'Finance'})
        self.emp_role, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee'})

        # Department
        self.dept_it = Department.objects.create(name="IT Test Dept", code="IT_T")
        self.dept_fin = Department.objects.create(name="Finance Test Dept", code="FIN_T")

        # Grades
        self.grade = EmployeeGrade.objects.create(name="Grade 3", code="G3_T", rank=3)

        # Positions
        self.pos_emp = Position.objects.create(name="Developer", department=self.dept_it, code="DEV_T")
        self.pos_fin = Position.objects.create(name="Finance Manager", department=self.dept_fin, code="FIN_MGR_T")

        # Superadmin
        self.superadmin = User.objects.create_superuser(
            username="rbac.superadmin", email="sup@t.test", password="Pass123!"
        )

        # Rector (is_staff=False, not superuser)
        self.rector = User.objects.create_user(
            username="rbac.rector", email="rector@t.test", password="Pass123!"
        )
        self.rector.roles.add(self.rector_role)

        # Vice Rector
        self.vice_rector = User.objects.create_user(
            username="rbac.vr", email="vr@t.test", password="Pass123!"
        )
        self.vice_rector.roles.add(self.vr_role)

        # Department Head
        self.dept_head = User.objects.create_user(
            username="rbac.dh", email="dh@t.test", password="Pass123!",
            department=self.dept_it,
        )
        self.dept_head.roles.add(self.dh_role)

        # HR Manager
        self.hr_user = User.objects.create_user(
            username="rbac.hr", email="hr@t.test", password="Pass123!",
        )
        self.hr_user.roles.add(self.hr_role)
        self.hr_perm, _ = HRPermissionConfig.objects.get_or_create(
            user=self.hr_user,
            defaults={
                'can_view_payroll': True,
                'can_manage_salary': True,
                'can_manage_payroll': True,
                'can_approve_payroll': True,
                'can_mark_paid': True,
                'can_view_payroll_reports': True,
            }
        )

        # Finance Manager
        self.finance_user = User.objects.create_user(
            username="rbac.finance", email="finance@t.test", password="Pass123!",
            department=self.dept_fin,
        )
        self.finance_user.roles.add(self.finance_role)
        self.finance_perm, _ = PayrollPermissionConfig.objects.get_or_create(
            user=self.finance_user,
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
            }
        )

        # Employee A (IT dept)
        self.emp_a = User.objects.create_user(
            username="rbac.emp.a", email="empa@t.test", password="Pass123!",
            department=self.dept_it, position=self.pos_emp, grade=self.grade,
        )
        self.emp_a.roles.add(self.emp_role)

        # Employee B (Finance dept)
        self.emp_b = User.objects.create_user(
            username="rbac.emp.b", email="empb@t.test", password="Pass123!",
            department=self.dept_fin,
        )
        self.emp_b.roles.add(self.emp_role)

        # Payroll period
        self.period = PayrollPeriod.objects.create(
            name="RBAC Test Period",
            code="2026-RBAC",
            period_type=PayrollPeriod.PeriodType.MONTHLY,
            start_date=timezone.datetime(2026, 10, 1).date(),
            end_date=timezone.datetime(2026, 10, 31).date(),
            status=PayrollPeriod.Status.OPEN,
            created_by=self.rector,
        )

        # Salary profile for emp_a
        create_salary_profile(
            actor=self.rector, user=self.emp_a, base_salary=Decimal("10000000.00")
        )

        # Payroll record for emp_a
        self.record_a = calculate_payroll(self.emp_a, self.period, actor=self.rector)
        approve_payroll_record(self.rector, self.record_a)

        self.client = Client()

    # -------------------------------------------------------------------------
    # 1. can_view_user_salary — object-level permission function
    # -------------------------------------------------------------------------

    def test_superadmin_can_view_any_salary(self):
        self.assertTrue(can_view_user_salary(self.superadmin, self.emp_a))
        self.assertTrue(can_view_user_salary(self.superadmin, self.emp_b))
        self.assertTrue(can_view_user_salary(self.superadmin, self.rector))

    def test_user_can_view_own_salary(self):
        self.assertTrue(can_view_user_salary(self.emp_a, self.emp_a))
        self.assertTrue(can_view_user_salary(self.rector, self.rector))
        self.assertTrue(can_view_user_salary(self.dept_head, self.dept_head))
        self.assertTrue(can_view_user_salary(self.vice_rector, self.vice_rector))

    def test_finance_can_view_any_salary(self):
        self.assertTrue(can_view_user_salary(self.finance_user, self.emp_a))
        self.assertTrue(can_view_user_salary(self.finance_user, self.emp_b))
        self.assertTrue(can_view_user_salary(self.finance_user, self.rector))

    def test_hr_with_salary_permission_can_view_salary(self):
        self.assertTrue(can_view_user_salary(self.hr_user, self.emp_a))

    def test_rector_cannot_view_other_employee_salary(self):
        """Rector must NOT view individual employee salaries — aggregate only."""
        self.assertFalse(can_view_user_salary(self.rector, self.emp_a))
        self.assertFalse(can_view_user_salary(self.rector, self.emp_b))

    def test_vice_rector_cannot_view_employee_salary(self):
        """Vice Rector must NOT view individual employee salaries."""
        self.assertFalse(can_view_user_salary(self.vice_rector, self.emp_a))
        self.assertFalse(can_view_user_salary(self.vice_rector, self.emp_b))

    def test_dept_head_cannot_view_subordinate_salary(self):
        """Department Head must NOT view any subordinate's individual salary."""
        self.assertFalse(can_view_user_salary(self.dept_head, self.emp_a))
        self.assertFalse(can_view_user_salary(self.dept_head, self.emp_b))

    def test_employee_cannot_view_peer_salary(self):
        """Ordinary employee must NOT view another employee's salary."""
        self.assertFalse(can_view_user_salary(self.emp_a, self.emp_b))
        self.assertFalse(can_view_user_salary(self.emp_b, self.emp_a))

    # -------------------------------------------------------------------------
    # 2. can_view_payroll_record — object-level permission function
    # -------------------------------------------------------------------------

    def test_superadmin_can_view_any_record(self):
        self.assertTrue(can_view_payroll_record(self.superadmin, self.record_a))

    def test_employee_can_view_own_approved_record(self):
        self.assertTrue(can_view_payroll_record(self.emp_a, self.record_a))

    def test_finance_can_view_any_record(self):
        self.assertTrue(can_view_payroll_record(self.finance_user, self.record_a))

    def test_hr_can_view_any_record(self):
        self.assertTrue(can_view_payroll_record(self.hr_user, self.record_a))

    def test_rector_cannot_view_individual_record(self):
        """Rector must NOT be able to view individual payroll records."""
        self.assertFalse(can_view_payroll_record(self.rector, self.record_a))

    def test_vice_rector_cannot_view_individual_record(self):
        """Vice Rector must NOT view individual payroll records."""
        self.assertFalse(can_view_payroll_record(self.vice_rector, self.record_a))

    def test_dept_head_cannot_view_subordinate_record(self):
        """Department Head must NOT view any individual payroll record."""
        self.assertFalse(can_view_payroll_record(self.dept_head, self.record_a))

    def test_employee_cannot_view_peer_record(self):
        """Employee B must NOT view Employee A's record."""
        self.assertFalse(can_view_payroll_record(self.emp_b, self.record_a))

    def test_employee_cannot_view_own_draft_record(self):
        """Employees may NOT view their own draft (not yet approved) record."""
        # Use a different period to avoid the unique_employee_payroll_per_period constraint
        draft_period = PayrollPeriod.objects.create(
            name="Draft Test Period",
            code="2026-DRAFT",
            period_type=PayrollPeriod.PeriodType.MONTHLY,
            start_date=timezone.datetime(2026, 11, 1).date(),
            end_date=timezone.datetime(2026, 11, 30).date(),
            status=PayrollPeriod.Status.OPEN,
            created_by=self.rector,
        )
        draft_record = PayrollRecord.objects.create(
            employee=self.emp_a,
            period=draft_period,
            base_salary=Decimal("10000000"),
            gross_salary=Decimal("10000000"),
            net_salary=Decimal("9000000"),
            tax_total=Decimal("1000000"),
            total_deductions=Decimal("0"),
            kpi_bonus=Decimal("0"),
            currency="UZS",
            status=PayrollRecord.Status.DRAFT,
            payment_status=PayrollRecord.PaymentStatus.UNPAID,
            employee_name_snapshot=self.emp_a.display_name,
            employee_username_snapshot=self.emp_a.username,
            department_snapshot="IT Test Dept",
        )
        self.assertFalse(can_view_payroll_record(self.emp_a, draft_record))

    # -------------------------------------------------------------------------
    # 3. can_manage_salary permission function
    # -------------------------------------------------------------------------

    def test_superadmin_can_manage_salary(self):
        self.assertTrue(can_manage_salary(self.superadmin))

    def test_finance_can_manage_salary(self):
        self.assertTrue(can_manage_salary(self.finance_user))

    def test_hr_with_permission_can_manage_salary(self):
        self.assertTrue(can_manage_salary(self.hr_user))

    def test_rector_cannot_manage_salary(self):
        """Rector must NOT be able to edit/manage individual salaries."""
        self.assertFalse(can_manage_salary(self.rector))

    def test_vice_rector_cannot_manage_salary(self):
        self.assertFalse(can_manage_salary(self.vice_rector))

    def test_dept_head_cannot_manage_salary(self):
        self.assertFalse(can_manage_salary(self.dept_head))

    def test_employee_cannot_manage_salary(self):
        self.assertFalse(can_manage_salary(self.emp_a))

    # -------------------------------------------------------------------------
    # 4. can_approve_payroll — Rector can approve; Finance cannot by default
    # -------------------------------------------------------------------------

    def test_rector_can_approve_payroll(self):
        self.assertTrue(can_approve_payroll(self.rector))

    def test_finance_cannot_approve_payroll_by_default(self):
        """Finance Manager by default has can_approve_payroll=False."""
        self.assertFalse(can_approve_payroll(self.finance_user))

    def test_superadmin_can_approve_payroll(self):
        self.assertTrue(can_approve_payroll(self.superadmin))

    # -------------------------------------------------------------------------
    # 5. get_payroll_permission helper
    # -------------------------------------------------------------------------

    def test_get_payroll_permission_finance_view(self):
        self.assertTrue(get_payroll_permission(self.finance_user, 'can_view_payroll'))

    def test_get_payroll_permission_finance_reports(self):
        self.assertTrue(get_payroll_permission(self.finance_user, 'can_view_payroll_reports'))

    def test_get_payroll_permission_finance_approve_false(self):
        self.assertFalse(get_payroll_permission(self.finance_user, 'can_approve_payroll'))

    def test_get_payroll_permission_superadmin_all(self):
        self.assertTrue(get_payroll_permission(self.superadmin, 'can_view_payroll'))
        self.assertTrue(get_payroll_permission(self.superadmin, 'can_manage_salary'))
        self.assertTrue(get_payroll_permission(self.superadmin, 'can_approve_payroll'))

    def test_get_payroll_permission_employee_all_false(self):
        for field in ['can_view_payroll', 'can_manage_salary', 'can_approve_payroll', 'can_mark_paid']:
            self.assertFalse(get_payroll_permission(self.emp_a, field))

    # -------------------------------------------------------------------------
    # 6. HTTP IDOR Tests: Cross-employee URL access returns 403
    # -------------------------------------------------------------------------

    def test_employee_cannot_access_peer_record_detail_url(self):
        """Employee B must get 403 when accessing Employee A's record detail URL."""
        self.client.login(username="rbac.emp.b", password="Pass123!")
        url = reverse('payroll:record_detail', kwargs={'pk': self.record_a.pk})
        response = self.client.get(url)
        self.assertIn(response.status_code, [403, 302])

    def test_rector_cannot_access_individual_record_detail_url(self):
        """Rector must get 403 when accessing any individual payroll record detail."""
        self.client.login(username="rbac.rector", password="Pass123!")
        url = reverse('payroll:record_detail', kwargs={'pk': self.record_a.pk})
        response = self.client.get(url)
        self.assertIn(response.status_code, [403, 302])

    def test_dept_head_cannot_access_record_detail_url(self):
        """Department Head must get 403 when accessing any individual record detail."""
        self.client.login(username="rbac.dh", password="Pass123!")
        url = reverse('payroll:record_detail', kwargs={'pk': self.record_a.pk})
        response = self.client.get(url)
        self.assertIn(response.status_code, [403, 302])

    def test_employee_cannot_access_peer_pdf_url(self):
        """Employee B must get 403 when downloading Employee A's payslip PDF."""
        self.client.login(username="rbac.emp.b", password="Pass123!")
        url = reverse('payroll:record_pdf', kwargs={'pk': self.record_a.pk})
        response = self.client.get(url)
        self.assertIn(response.status_code, [403, 302])

    def test_rector_cannot_access_pdf_url(self):
        """Rector must get 403 when accessing individual payslip PDF."""
        self.client.login(username="rbac.rector", password="Pass123!")
        url = reverse('payroll:record_pdf', kwargs={'pk': self.record_a.pk})
        response = self.client.get(url)
        self.assertIn(response.status_code, [403, 302])

    def test_employee_can_access_own_pdf(self):
        """Employee A CAN access their own payslip PDF (approved/paid record)."""
        self.client.login(username="rbac.emp.a", password="Pass123!")
        url = reverse('payroll:record_pdf', kwargs={'pk': self.record_a.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_finance_can_access_any_pdf(self):
        """Finance Manager CAN access any employee's payslip PDF."""
        self.client.login(username="rbac.finance", password="Pass123!")
        url = reverse('payroll:record_pdf', kwargs={'pk': self.record_a.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_employee_cannot_access_excel_export(self):
        """Employee must get 403 on the period Excel export endpoint."""
        self.client.login(username="rbac.emp.a", password="Pass123!")
        url = reverse('payroll:period_export_excel', kwargs={'pk': self.period.pk})
        response = self.client.get(url)
        self.assertIn(response.status_code, [403, 302])

    def test_rector_cannot_access_excel_export(self):
        """Rector must get 403 on the period Excel export (salary privacy)."""
        self.client.login(username="rbac.rector", password="Pass123!")
        url = reverse('payroll:period_export_excel', kwargs={'pk': self.period.pk})
        response = self.client.get(url)
        self.assertIn(response.status_code, [403, 302])

    def test_dept_head_cannot_access_excel_export(self):
        """Department Head must get 403 on Excel export."""
        self.client.login(username="rbac.dh", password="Pass123!")
        url = reverse('payroll:period_export_excel', kwargs={'pk': self.period.pk})
        response = self.client.get(url)
        self.assertIn(response.status_code, [403, 302])

    def test_finance_can_access_excel_export(self):
        """Finance Manager CAN access period Excel export."""
        self.client.login(username="rbac.finance", password="Pass123!")
        url = reverse('payroll:period_export_excel', kwargs={'pk': self.period.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    # -------------------------------------------------------------------------
    # 7. Payroll Record List queryset scoping
    # -------------------------------------------------------------------------

    def test_employee_record_list_only_own_records(self):
        """Employee sees only their own records in the payroll record list."""
        # Create a salary and record for emp_b to pollute
        create_salary_profile(actor=self.rector, user=self.emp_b, base_salary=Decimal("8000000.00"))
        calculate_payroll(self.emp_b, self.period, actor=self.rector)

        self.client.login(username="rbac.emp.a", password="Pass123!")
        url = reverse('payroll:record_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        records = response.context.get('records', [])
        for r in records:
            self.assertEqual(r.employee_id, self.emp_a.pk)

    def test_rector_record_list_only_own_records(self):
        """Rector should only see their own records in payroll:record_list."""
        self.client.login(username="rbac.rector", password="Pass123!")
        url = reverse('payroll:record_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        records = response.context.get('records', [])
        for r in records:
            self.assertEqual(r.employee_id, self.rector.pk)

    def test_finance_record_list_sees_all_records(self):
        """Finance Manager sees all records in payroll:record_list."""
        self.client.login(username="rbac.finance", password="Pass123!")
        url = reverse('payroll:record_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    # -------------------------------------------------------------------------
    # 8. My Salary self-service view
    # -------------------------------------------------------------------------

    def test_my_salary_view_accessible_to_any_authenticated_user(self):
        for username in ['rbac.emp.a', 'rbac.rector', 'rbac.dh', 'rbac.finance', 'rbac.hr']:
            self.client.login(username=username, password="Pass123!")
            url = reverse('payroll:my_salary')
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, f"My Salary failed for {username}")

    def test_my_salary_view_unauthenticated_redirects(self):
        self.client.logout()
        url = reverse('payroll:my_salary')
        response = self.client.get(url)
        self.assertIn(response.status_code, [302])

    # -------------------------------------------------------------------------
    # 9. Finance role is_finance property
    # -------------------------------------------------------------------------

    def test_finance_user_is_finance_true(self):
        self.assertTrue(self.finance_user.is_finance)

    def test_employee_is_finance_false(self):
        self.assertFalse(self.emp_a.is_finance)

    def test_rector_is_finance_false(self):
        self.assertFalse(self.rector.is_finance)

    def test_superadmin_is_finance_false(self):
        self.assertFalse(self.superadmin.is_finance)

    # -------------------------------------------------------------------------
    # 10. Dashboard: leadership roles get no individual records in context
    # -------------------------------------------------------------------------

    def test_dashboard_rector_no_individual_records(self):
        """Rector dashboard context must NOT include individual payroll records."""
        self.client.login(username="rbac.rector", password="Pass123!")
        url = reverse('payroll:dashboard')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        recent = response.context.get('recent_records')
        # Should be empty queryset — no individual records for leadership
        self.assertEqual(len(list(recent)), 0)

    def test_dashboard_dept_head_no_individual_records(self):
        """Dept Head dashboard must NOT return individual records."""
        self.client.login(username="rbac.dh", password="Pass123!")
        url = reverse('payroll:dashboard')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        recent = response.context.get('recent_records')
        self.assertEqual(len(list(recent)), 0)

    def test_dashboard_finance_sees_individual_records(self):
        """Finance Manager dashboard CAN see individual records."""
        self.client.login(username="rbac.finance", password="Pass123!")
        url = reverse('payroll:dashboard')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # Finance should receive view_type UNIVERSITY and can see recent_records
        view_type = response.context.get('view_type')
        self.assertEqual(view_type, 'UNIVERSITY')

