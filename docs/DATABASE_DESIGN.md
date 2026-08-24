# Database Design

## Database

Use PostgreSQL with normalized relational models. UUID primary keys are recommended for externally exposed object identifiers; integer primary keys are acceptable internally if URL access is always permission checked.

All major business tables should include:

- `created_at`
- `updated_at`
- `created_by` where meaningful
- `is_archived` or explicit archive state where meaningful

## Entity Groups

## Accounts

### User

Use a custom Django user model from the start.

Key fields:

- username or email
- first name
- last name
- middle name optional
- phone optional
- preferred language
- is_active
- is_staff
- is_superuser

Relationships:

- user has one current employee profile or organization membership record
- user has many role assignments

### Role

Canonical role codes:

- `RECTOR`
- `VICE_RECTOR`
- `DEPARTMENT_HEAD`
- `EMPLOYEE`

Roles may be stored in a role table or mapped through Django groups. Use stable role codes.

### Permission

Use Django permissions for coarse-grained capabilities, combined with custom object-level policy checks.

## Organization

### University

Fields:

- name
- logo
- timezone
- active flag

### OrganizationalUnit

Future expansion model for hierarchy.

Fields:

- name
- unit_type
- parent
- active flag

### Department

Fields:

- university
- organizational unit optional
- name
- code
- active flag

Indexes:

- `department.code`
- `department.active`

### Position

Fields:

- department optional for department-specific positions
- name
- code
- active flag

### DepartmentResponsibility

Maps Vice Rectors to departments.

Fields:

- vice_rector user
- department
- start date
- end date optional
- active flag

Unique active responsibility should prevent duplicate active rows for the same Vice Rector and department.

### EmployeeProfile

Fields:

- user
- department
- position
- employment status
- hire date
- manager optional

Indexes:

- `department`
- `position`
- `employment_status`

## Tasks

### Task

Fields:

- title
- description
- creator
- department
- task_type
- priority
- complexity
- status
- start_date
- deadline
- progress
- official_deadline_changed_at
- cancelled_at
- archived_at

Relationships:

- task belongs to one department
- task has many assignments
- task has many comments, notes, attachments, submissions, approvals, history events, deadline changes

Indexes:

- `status`
- `department`
- `creator`
- `deadline`
- `(department, status)`
- `(department, deadline)`
- `(status, deadline)`

### TaskType

Fields:

- name
- code
- active flag
- default complexity optional

### TaskAssignment

Supports multi-employee assignment.

Fields:

- task
- employee user
- assigned_by
- assigned_at
- accepted_at
- status
- role in task optional

Indexes:

- `(task, employee)`
- `employee`
- `status`

### SubTask

Future-ready subtask support.

Fields:

- parent task
- title
- description
- assigned employee optional
- status
- deadline
- progress

### TaskDependency

Fields:

- task
- depends_on_task
- dependency_type

Prevent self-dependencies and cycles at service level.

### TaskTemplate

Fields:

- title
- description
- task_type
- default priority
- default complexity
- default duration
- active flag

### RecurringTask

Fields:

- template
- schedule expression
- next_run_at
- created_by
- department
- active flag

## Task Work Artifacts

### TaskSubmission

Fields:

- task
- submitted_by
- submitted_at
- comment
- status
- version number

### TaskAttachment

Fields:

- task
- submission optional
- uploaded_by
- original_filename
- stored_filename
- extension
- mime_type
- size
- storage_path
- checksum
- uploaded_at
- deleted_at optional

Downloads must go through controlled views.

### TaskComment

Reusable user-visible discussion/comment model.

Fields:

- task
- author
- comment_type
- body
- visibility scope
- created_at
- updated_at

### TaskNote

Private or role-scoped note model.

Fields:

- task
- author
- note_type
- body
- visibility scope
- created_at

### TaskApproval

Fields:

- task
- level (`FIRST`, `SECOND`)
- requested_by
- approver
- decision (`APPROVED`, `REJECTED`)
- decision_at
- comment
- related submission

Indexes:

- `(task, level)`
- `approver`
- `decision`

### TaskRejection

Can be separate or represented by `TaskApproval.decision = REJECTED`. Keep a separate model only if rejection-specific reporting becomes complex.

Recommended fields if separate:

- task
- approval
- rejected_by
- level
- reason
- rejected_at

### TaskHistory

Business timeline events.

Fields:

- task
- actor
- event_type
- old_status
- new_status
- metadata JSON
- created_at

### DeadlineChange

Fields:

- task
- old_deadline
- new_deadline
- reason
- changed_by
- changed_at

Only Rector or responsible Vice Rector can create official deadline changes.

## Notifications

### Notification

Fields:

- target_user
- notification_type
- title key
- message key
- context JSON
- related content type
- related object id
- read_at
- created_at

Indexes:

- `(target_user, read_at)`
- `(target_user, created_at)`
- `notification_type`

## Audit

### AuditLog

Fields:

- actor user nullable
- action
- content type
- object id
- timestamp
- ip address
- user agent
- old_value JSON
- new_value JSON
- reason
- correlation id

Indexes:

- `actor`
- `action`
- `timestamp`
- `(content_type, object_id)`

## KPI

### KPIRule

Fields:

- code
- name
- period type
- weight
- metric source
- condition JSON
- formula JSON or expression reference
- active flag
- effective_from
- effective_to

### KPI

Represents calculated KPI for one user and period.

Fields:

- employee
- period type
- period start
- period end
- score
- status
- calculated_at

### KPISnapshot

Immutable KPI result details.

Fields:

- kpi
- source data JSON
- rule results JSON
- final score
- created_at

## Payroll

### PayrollRule

Fields:

- code
- name
- rule_type
- configuration JSON
- active flag
- effective_from
- effective_to

### Payroll

Fields:

- employee
- period start
- period end
- base_salary
- kpi_bonus
- additional_bonus
- deduction
- calculated_salary
- status
- generated_by
- generated_at

### SalaryAdjustment

Fields:

- payroll
- employee
- adjustment_type
- amount
- reason
- created_by
- created_at

## Settings

### SystemSetting

Fields:

- key
- value JSON
- value type
- updated_by
- updated_at

Examples:

- university name
- logo
- favicon
- timezone
- date format
- file size limit
- allowed extensions
- notification settings
- deadline rules
- KPI rules
- payroll rules

## Normalization Notes

- Keep role codes, task status codes, priority codes, and approval levels stable and language-neutral.
- Use lookup tables for configurable task types, priorities, and complexity levels when administrators need to manage them.
- Use JSON only for configurable rule definitions, metadata, audit diffs, and notification context. Do not store core relational relationships only in JSON.
- Preserve historical records instead of overwriting important decisions.

