# Payroll Architecture

## Phase Status & Scope

**Phase 8: Payroll & Compensation Engine with Strict Role Governance & Privacy** is fully implemented.

The system supports end-to-end KPI-based salary, allowance, deduction, and bonus calculation with snapshot immutability, individual privacy guarantees, and role-based segregation of duty:

`Gross Salary (Base + Allowances + Bonuses + KPI Performance Bonus) - Deductions - Taxes = Net Salary`

The system is not a general-ledger accounting tool; it is a specialized university compensation engine integrating task completion, KPI scoring, and strict salary privacy.

---

## Core Models

### 1. `SalaryProfile`
Employee compensation configuration defining base pay, payment method, bank details, and active status.
- Confidential: visible only to employee themselves, Finance team, and authorized HR officers.
- Rector and leadership do not see individual base salaries.

### 2. `SalaryHistory`
Audit record tracking historical changes to employee compensation, effective dates, and authorizing officer.

### 3. `PayrollPeriod`
Monthly or ad-hoc calculation period with status tracking (`DRAFT`, `OPEN`, `CALCULATING`, `CALCULATED`, `SUBMITTED`, `APPROVED`, `PAID`, `CLOSED`, `CANCELLED`).

### 4. `PayrollRecord`
Snapshot record for an individual employee in a payroll period:
- Captures frozen baseline values (`employee_name_snapshot`, `department_name_snapshot`, `position_name_snapshot`, `base_salary_snapshot`).
- Holds computed `total_allowances`, `total_bonuses`, `kpi_score_snapshot`, `kpi_bonus`, `total_deductions`, `gross_salary`, `tax_total`, `net_salary`.
- Payment status (`PENDING`, `PROCESSING`, `PAID`, `FAILED`) and disbursement reference.

### 5. `PayrollLine`
Itemized line-item breakdown (allowances, bonuses, KPI bonus, deductions, income taxes, pension fund).

### 6. `PayrollAdjustment`
One-time or periodic salary adjustments (bonuses, overtime, deductions, advances) requiring formal approval before inclusion in payroll calculation.

### 7. `PayrollPermissionConfig`
Granular user-level capability configuration granting explicit operational permissions (`can_view_payroll`, `can_manage_salary`, `can_calculate_payroll`, `can_approve_payroll`, `can_mark_paid`, `can_view_payroll_reports`, etc.).

---

## Strict Privacy & Access Control (Phase 8 Governance)

### Individual Salary Privacy Policy
Individual employee compensation data is strictly confidential:
- **Employees**:
  - ✅ Can view their own salary profile, salary history, payslips, and personal payroll status.
  - ❌ Cannot view any other employee's salary or payslips.
  - ❌ Direct URL or IDOR attempts return `403 Forbidden`.
- **Rector & Vice Rectors**:
  - ✅ Can view university-wide and departmental **aggregated data only** (total payroll spend, departmental summaries, averages, paid employee counts).
  - ❌ Cannot view individual employee salaries or payslips.
  - ❌ Cannot create, edit, or adjust individual salaries (role separation of duty).
- **Department Heads**:
  - ✅ Can view **aggregated departmental summaries only** for their department.
  - ❌ Cannot view individual employee salaries, salary history, or individual payroll records (even for subordinates in their department; returns `403 Forbidden`).
- **Finance & Payroll Officers**:
  - ✅ Have operational access to calculate payroll, configure salary profiles, manage adjustments, generate payslips, and mark disbursements.
  - Required permissions are verified at the model/service level and view dispatch level.

---

## Role & Permission Matrix

| Role | Individual Salary (Self) | Individual Salary (Others) | Aggregated Payroll | Calculate / Manage Payroll | Approve Payroll | Disburse / Mark Paid |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Technical Superadmin** | Yes | Technical/System | Full | System | System | System |
| **Rector** | Yes | ❌ No | ✅ University Aggregates | ❌ No | ❌ No | ❌ No |
| **Vice Rector** | Yes | ❌ No | ✅ Scoped Dept Aggregates | ❌ No | ❌ No | ❌ No |
| **Department Head** | Yes | ❌ No | ✅ Own Dept Aggregates | ❌ No | ❌ No | ❌ No |
| **Finance Officer** | Yes | ✅ Authorized Ops | ✅ Operational Reports | ✅ Yes | ✅ Yes (if delegated) | ✅ Yes |
| **HR Manager** | Yes | ✅ If permitted in HR Config | ✅ Operational Reports | ❌ No (Finance only) | ❌ No | ❌ No |
| **Employee** | ✅ Yes (Own Only) | ❌ No | ❌ No | ❌ No | ❌ No | ❌ No |

---

## KPI Integration & Snapshot Integrity

- Payroll calculation integrates with the `kpi` app via `calculate_kpi_bonus()`.
- Uses finalized `KPIRecord` scores for the corresponding period without recalculating task metrics.
- All historical payroll outputs are immutable snapshots: modifications to base salary profiles or tax rules after period approval never mutate existing records.

---

## Audit & Governance Logging

All payroll and security-sensitive events are audited in `AuditLog`:
- `SALARY_CREATED`, `SALARY_UPDATED`, `SALARY_DEACTIVATED`, `SALARY_CHANGED`, `SALARY_VIEWED`
- `PAYROLL_PERIOD_CREATED`, `PAYROLL_CALCULATED`, `PAYROLL_SUBMITTED`, `PAYROLL_APPROVED`, `PAYROLL_PAID`, `PAYROLL_CLOSED`
- `PAYROLL_ADJUSTMENT_CREATED`, `PAYROLL_ADJUSTMENT_APPROVED`
- `ROLE_ASSIGNED`, `ROLE_REMOVED`, `FINANCE_ROLE_ASSIGNED`, `PAYROLL_PERMISSION_CHANGED`


