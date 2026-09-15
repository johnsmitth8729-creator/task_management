# RBAC and Permissions Architecture

## Core Security Principle

Frontend hiding is not security. Every sensitive operation is validated on the backend using role authority, object ownership, and departmental scoping across querysets, service methods, and object-level permission guards.

---

## 1. Primary Roles

The platform enforces a strict separation between technical system administration, university leadership, departmental execution, and specialized financial operations:

1. **`TECHNICAL SUPERADMIN`** (`is_staff=True, is_superuser=True`, e.g., `superadmin`):
   - Highest technical and system authority.
   - Manages entire technical platform, technical user credentials, role permissions, system configuration, audit logs, and Django Admin (`/admin/`).
   - Can manage the Rector account technically.
   - Isolated from operational day-to-day university workflow execution.

2. **`RECTOR`** (`has_role('RECTOR')`, `is_staff=False, is_superuser=False`, e.g., `rector`):
   - Highest operational university authority.
   - Operates entirely through the standard application UI (does not use Django Admin).
   - University-wide visibility over tasks, departments, vice rectors, and operational deliverables.
   - Authorizes high-level tasks, task types, templates, and grants final approval on completed deliverables.
   - **Payroll Scope**: Sees **aggregated university-wide metrics only**. Forbidden from viewing individual employee salaries or managing/editing salaries directly.

3. **`VICE RECTOR`** (`has_role('VICE_RECTOR')`, `is_staff=False, is_superuser=False`, e.g., `vice.rector`):
   - University executive supervising one or more assigned departments via `DepartmentResponsibility`.
   - Scoped strictly to supervised departments and their tasks/employees.
   - Authorizes new tasks for assigned departments and conducts Level 2 (Second/Final) approvals for assigned departments.
   - Has read-only visibility into operational employee directory in supervised departments.
   - **Payroll Scope**: Sees **aggregated department metrics only** for supervised departments. Forbidden from viewing individual employee salaries.

4. **`DEPARTMENT HEAD`** (`has_role('DEPARTMENT_HEAD')`, `is_staff=False, is_superuser=False`, e.g., `department.head`):
   - Operational manager of a single department (`user.department`).
   - Scoped strictly to own department deliverables and staff.
   - Distributes tasks to department employees, monitors progress, and conducts Level 1 (First) submission approvals.
   - **Payroll Scope**: Sees **aggregated department totals only** for own department. Forbidden from viewing individual salaries or payslips of subordinates (returns `403 Forbidden`).

5. **`FINANCE OFFICER`** (`has_role('FINANCE')`, e.g., `finance.officer`):
   - Specialized financial operational authority.
   - Manages compensation configurations, salary profiles, and adjustment requests.
   - Executes payroll period calculations, generates payslips, and marks disbursement.
   - Governed by explicit `PayrollPermissionConfig` flags.

6. **`HR MANAGER`** (`has_role('HR')`, e.g., `hr.manager`):
   - Personnel lifecycle manager governed by `HRPermissionConfig`.
   - Manages employee profiles, positions, grades, and supervisors.
   - Can hold delegated payroll view/management permissions if authorized by Rector.

7. **`EMPLOYEE`** (`has_role('EMPLOYEE')`, `is_staff=False, is_superuser=False`, e.g., `employee.one`, `employee.two`):
   - Task executor within a department.
   - Scoped strictly to tasks directly assigned to them (`TaskAssignment`).
   - Accepts incoming tasks, updates progress (0-100%), adds work notes, attaches work evidence & reports, and submits deliverables for approval.
   - **Payroll Scope**: **Strict Individual Privacy**. Can view their own salary profile, history, payslips, and payroll status. Cannot view any other employee's salary or payslip (returns `403 Forbidden`).

---

## 2. Permission Matrix

| Capability | Technical Superadmin | Rector | Vice Rector | Department Head | Finance Officer | Employee |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Django Admin Access** (`/admin/`) | **Yes** | No | No | No | No | No |
| **System Settings & Audit Logs** | **Yes** | Operational Logs Only | No | No | No | No |
| **Manage Technical Roles & Staff** | **Yes** | No | No | No | No | No |
| **Create / Edit University Structure** | **Yes** | **Yes** | No | No | No | No |
| **Create / Manage Tasks** | **Yes** | **Yes** (All) | **Yes** (Scoped Depts) | No | No | No |
| **Assign Task to Department** | **Yes** | **Yes** (All) | **Yes** (Scoped Depts) | No | No | No |
| **Distribute Task to Employees** | **Yes** | **Yes** (All) | **Yes** (Scoped Depts) | **Yes** (Own Dept) | No | No |
| **Accept Task & Update Progress** | No | No | No | No | No | **Yes** (Own Assigned) |
| **Submit Task Deliverable** | No | No | No | No | No | **Yes** (Own Assigned) |
| **First Approval (Level 1)** | **Yes** (Override) | **Yes** (Override) | No (by default) | **Yes** (Own Dept) | No | No |
| **Second / Final Approval (Level 2)** | **Yes** (Override) | **Yes** (All) | **Yes** (Scoped Depts) | No | No | No |
| **Reject Task with Mandatory Reason** | **Yes** | **Yes** (Stage 2) | **Yes** (Stage 2 Scoped) | **Yes** (Stage 1 Dept) | No | No |
| **Extend Task Deadline** | **Yes** | **Yes** (All) | **Yes** (Scoped Depts) | No | No | No |
| **Upload Work Evidence & Files** | **Yes** | **Yes** | **Yes** (Scoped Depts) | **Yes** (Own Dept) | No | **Yes** (Assigned Task) |
| **Download / View Protected Files** | **Yes** | **Yes** (All) | **Yes** (Scoped Depts) | **Yes** (Own Dept) | No | **Yes** (Assigned Task) |
| **View Own Salary & Payslips** | **Yes** | **Yes** (Self) | **Yes** (Self) | **Yes** (Self) | **Yes** (Self) | **Yes** (Self) |
| **View Other Employees' Salaries** | **Yes** | ❌ **No** | ❌ **No** | ❌ **No** | **Yes** (Operational) | ❌ **No (403)** |
| **View Aggregated Payroll Reports** | **Yes** | **Yes** (Global) | **Yes** (Scoped Depts) | **Yes** (Own Dept) | **Yes** (Operational) | ❌ **No** |
| **Calculate / Execute Payroll** | **Yes** | ❌ **No** | ❌ **No** | ❌ **No** | **Yes** (Finance) | ❌ **No** |
| **Approve / Disburse Payroll** | **Yes** | ❌ **No** | ❌ **No** | ❌ **No** | **Yes** (Finance) | ❌ **No** |
| **Electronically Sign Completed Task** | **Yes** (Admin) | **Yes** (All Depts) | **Yes** (Scoped Depts) | ❌ **No** | ❌ **No** | ❌ **No** |
| **Revoke Electronic Signature** | **Yes** | **Yes** | ❌ **No** | ❌ **No** | ❌ **No** | ❌ **No** |
| **Public Signature / QR Verification** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** |
| **View Executive Analytics & Trends** | **Yes** | **Yes** (Global) | **Yes** (Scoped Depts) | ❌ **No** | ❌ **No** | ❌ **No** |
| **View Department Analytics Dashboard** | **Yes** | **Yes** (All Depts) | **Yes** (Scoped Depts) | **Yes** (Own Dept) | ❌ **No** | ❌ **No** |
| **View Personal Performance Dashboard** | **Yes** (Self) | **Yes** (Self) | **Yes** (Self) | **Yes** (Self) | **Yes** (Self) | **Yes** (Self) |
| **View HR Workforce Analytics** | **Yes** | **Yes** | ❌ **No** | ❌ **No** | ❌ **No** | ❌ **No** (HR/Admin) |
| **View Payroll Financial Analytics** | **Yes** | **Yes** (Aggregated Only) | **Yes** (Aggregated Scoped) | **Yes** (Aggregated Dept) | **Yes** (Financial) | ❌ **No** |
| **Export Analytics Reports (PDF/XLSX/CSV)** | **Yes** | **Yes** (Scoped) | **Yes** (Scoped) | **Yes** (Scoped) | **Yes** (Scoped) | **Yes** (Own Scope) |


---

## 3. Queryset Scoping Implementation

### `get_scoped_tasks(user, include_archived=False)`
* **Superadmin & Rector**: `Task.objects.all()`
* **Vice Rector**: `Task.objects.filter(Q(responsible_department__in=scoped_depts) | Q(creator=user))`
* **Department Head**: `Task.objects.filter(responsible_department_id=user.department_id)`
* **Employee**: `Task.objects.filter(assignments__user=user)`

### `user.get_scoped_departments()`
* **Superadmin & Rector**: `Department.objects.all()`
* **Vice Rector**: `Department.objects.filter(id__in=user.department_responsibilities.filter(is_active=True).values('department_id'))`
* **Department Head & Employee**: `Department.objects.filter(id=user.department_id)`

### `user.get_scoped_users()`
* **Superadmin & Rector**: `User.objects.all()`
* **Vice Rector**: `User.objects.filter(department_id__in=scoped_dept_ids)` (Read-only operational directory)
* **Department Head**: `User.objects.filter(department_id=user.department_id)` (Read-only operational directory)
* **Employee**: `User.objects.filter(id=user.id)`

---

## 4. Evidence Immutability & File Security

1. **Protected Streaming**: Files are never served directly via open static URLs; access is routed through `TaskFileDownloadView` and `TaskFileInlineView` with RBAC authorization.
2. **Approved Evidence Immutability**: Any `TaskFile` attached to a `TaskSubmission` in `FIRST_APPROVED` or `FINAL_APPROVED` status is permanently locked and cannot be deleted or modified by any user.
3. **Soft-Deletion & Audit**: Deletion of active unapproved files is soft-deleted (`is_active=False`, `deleted_at=now()`, `deleted_by=user`) and logged in `AuditLog`.

---

## 5. Architectural Boundaries for Future Modules

To preserve clean modularity, future modules must interface cleanly without mixing responsibilities:

```
┌────────────────────────────────────────────────────────┐
│               HUMAN RESOURCES (HR Module)              │
│   Employee master data, contracts, positions, history  │
└───────────────────────────┬────────────────────────────┘
                            │ Employee Profiles & Org Chart
┌───────────────────────────▼────────────────────────────┐
│                TASK MANAGEMENT (Current)               │
│   Workflows, Assignments, Progress, Approvals, Evidence│
└───────────────────────────┬────────────────────────────┘
                            │ Deliverables & Completion Timestamps
┌───────────────────────────▼────────────────────────────┐
│              PERFORMANCE & KPI (Future)                │
│   KPI Indicators, Deadline Compliance, Quality Scores  │
└───────────────────────────┬────────────────────────────┘
                            │ Approved Performance Ratings
┌───────────────────────────▼────────────────────────────┐
│               FINANCE & PAYROLL (Future)               │
│   Salary calculation, bonuses, payroll distribution    │
└────────────────────────────────────────────────────────┘
```

* **Electronic Signature & QR Verification**:
  - The `TaskApproval` model records `stage`, `decision`, `actor`, `created_at`, `notes`, and attached `TaskSubmission` versions.
  - Future digital signing will hash this immutable record with a private key and generate a verifiable public QR verification URL referencing the cryptographic approval certificate.
