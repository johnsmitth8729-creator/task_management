# HR ARCHITECTURE & EMPLOYEE GOVERNANCE

## 1. Domain Overview
The `hr` application manages the employee directory, institutional profiles, staff grades (G1–G6), direct supervisor reporting lines, and Rector-controlled granular HR permissions.

---

## 2. Rector-Configured HR Permissions Matrix
Rector configures granular boolean flags in `HRPermissionConfig` for each HR officer:

| Flag | Description | Default for HR |
| :--- | :--- | :--- |
| `can_view_employees` | View full employee directory and institutional profiles | `True` |
| `can_create_employees` | Create new staff accounts in the portal | `False` (Rector-controlled) |
| `can_edit_employees` | Update profile information and contact details | `True` |
| `can_deactivate_employees`| Soft-deactivate staff accounts without deleting history | `False` (Rector-controlled) |
| `can_assign_department` | Place employees into departments | `True` |
| `can_assign_position` | Assign institutional job positions | `True` |
| `can_assign_grade` | Assign seniority grades (G1–G6) | `True` |
| `can_assign_supervisor` | Assign direct line supervisors | `True` |
| `can_manage_departments`| Create or edit university departments | `False` (Rector-only) |
| `can_assign_department_head` | Appoint department heads | `False` (Rector-only) |
| `can_assign_vice_rector_responsibility` | Assign vice rector sectors | `False` (Rector-only) |
| `can_view_kpi` | View employee KPI scorecards | `True` |
| `can_manage_kpi` | Assign and evaluate KPI indicators | `False` (Rector-controlled) |
| `can_approve_kpi` | Give final approval to KPI results | `False` (Rector-controlled) |

---

## 3. Employee Lifecycle & Data Immutability
- **Soft Deactivation**: When an employee departs or goes inactive (`is_active=False` / `employment_status=INACTIVE` / `TERMINATED`):
  - Account login is disabled.
  - Historical tasks, work evidence files, reports, submission versions, approvals, KPI evaluations, and audit logs are **100% preserved**.
- **Reactivation**: Can be restored by authorized HR or Rector at any time.
