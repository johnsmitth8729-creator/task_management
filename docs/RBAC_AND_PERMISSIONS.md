# RBAC and Permissions

## Security Rule

Frontend hiding is not security. Every sensitive operation must be checked on the backend using role, object ownership, and department scope.

## Roles

- `RECTOR`: superadmin-level university authority.
- `VICE_RECTOR`: administrator responsible for one or more assigned departments.
- `DEPARTMENT_HEAD`: manager of one department.
- `EMPLOYEE`: ordinary task executor.

## Scope Rules

### Rector

Can access and manage all university departments, users, tasks, approvals, analytics, KPI, payroll, settings, and audit records according to superadmin permissions.

### Vice Rector

Can access and manage only departments explicitly assigned through `DepartmentResponsibility`.

Vice Rector scope applies to:

- task creation
- task assignment to department
- second approval
- deadline changes
- department analytics
- department KPI views if permitted

### Department Head

Can access and manage only their own department.

Department Head can:

- view tasks assigned to their department
- assign employees in their department
- perform first approval
- reject first approval with reason
- view department-level analytics
- comment on department tasks

Department Head cannot:

- change official deadlines
- access other departments
- perform final approval unless also assigned a higher role
- view confidential payroll data unless explicitly permitted by policy

### Employee

Can access:

- tasks assigned directly to them
- permitted task comments/files/submissions for those tasks
- their own KPI summary where allowed

Employee cannot:

- access another employee's private task data by changing URL IDs
- assign official task owners
- approve their own task
- change official deadlines
- view department-wide confidential data
- view payroll data except their own permitted salary/bonus records, if enabled

## Permission Matrix

| Capability | Rector | Vice Rector | Department Head | Employee |
|---|---:|---:|---:|---:|
| Manage system settings | Yes | Limited if delegated | No | No |
| Manage all users | Yes | Scoped/limited | No | No |
| Manage department users | Yes | Assigned departments | Own department limited | No |
| Create task | Yes | Assigned departments | Optional internal tasks only if enabled | No |
| Assign task to any department | Yes | No | No | No |
| Assign task to assigned department | Yes | Yes | No | No |
| Assign task to employee | Yes | Assigned departments | Own department | No |
| View all tasks | Yes | No | No | No |
| View assigned department tasks | Yes | Yes | Own department | Only assigned tasks |
| Accept assigned task | No | No | No | Own assigned tasks |
| Submit task result | No | No | No | Own assigned tasks |
| First approval | Yes override | No by default | Own department | No |
| Second approval | Yes | Assigned departments | No | No |
| Reject with reason | Yes | Assigned departments at level 2 | Own department at level 1 | No |
| Change official deadline | Yes | Assigned departments | No | No |
| Upload files | Yes | Assigned task scope | Own department task scope | Own assigned tasks |
| Download files | Yes | Assigned department scope | Own department scope | Own assigned task scope |
| View analytics | Yes | Assigned departments | Own department | Own data only |
| View KPI | Yes | Assigned departments if permitted | Own department summary if permitted | Own KPI only |
| Manage KPI rules | Yes | Limited if delegated | No | No |
| View payroll | Yes | Limited if explicitly delegated | No by default | Own payroll only if enabled |
| Manage payroll rules | Yes | No by default | No | No |
| View audit logs | Yes | Scoped if delegated | No by default | No |

## Implementation Pattern

Use three layers:

1. Django model permissions for broad capability checks.
2. Selector/queryset scoping to restrict objects returned from the database.
3. Service-layer object policy checks before every state-changing operation.

Example policy functions:

- `can_view_task(user, task)`
- `can_assign_department(user, department)`
- `can_assign_employee(user, task, employee)`
- `can_accept_task(user, task)`
- `can_submit_task(user, task)`
- `can_first_approve(user, task)`
- `can_second_approve(user, task)`
- `can_change_deadline(user, task)`
- `can_download_attachment(user, attachment)`
- `can_view_payroll(user, payroll)`

## URL ID Protection

Views and APIs must never fetch sensitive objects with unrestricted `Model.objects.get(id=...)`.

Required pattern:

- get the authorized queryset for the current user
- fetch by id from that authorized queryset
- run service-level permission check before mutation

## Conflict Rule

If a user has multiple roles, use additive permissions only after each object scope is validated. Higher roles do not erase conflict-of-interest checks, such as approving one's own submission, unless an explicit override rule is documented.

## Ambiguities To Decide Later

- Whether Department Heads can create internal department tasks.
- Whether Vice Rectors can manage users in assigned departments or only tasks and approvals.
- Whether Rector can bypass first approval or must follow the same two-level process.

---

## Phase 2 — Implemented (accounts.permissions)

### Permission Helpers

```python
can_view_department(user, department) -> bool
can_manage_department(user, department) -> bool
can_view_user(actor, target_user) -> bool
can_edit_user(actor, target_user) -> bool
can_manage_roles(user) -> bool
can_manage_responsibilities(user) -> bool
```

### Class-Based View Mixins

```python
RectorRequiredMixin           # 403 if not Rector/superuser
ScopedDepartmentAccessMixin   # 403 if actor cannot view the department
ScopedUserAccessMixin         # 403 if actor cannot view the target user
```

### User Scoping Methods (accounts.models.User)

```python
user.is_rector             # True if RECTOR role or is_superuser
user.is_vice_rector        # True if VICE_RECTOR role
user.is_department_head    # True if DEPARTMENT_HEAD role
user.is_employee           # True if EMPLOYEE role
user.primary_role          # First Role object by priority
user.initials              # First letter of first + last name
user.get_scoped_departments()  # QuerySet<Department>
user.get_scoped_users()        # QuerySet<User>
```

Scoping rules:

| Role | `get_scoped_departments()` | `get_scoped_users()` |
|---|---|---|
| Rector | `Department.objects.all()` | `User.objects.all()` |
| Vice Rector | Departments from active `DepartmentResponsibility` | Users in those departments |
| Department Head | Own department only | Users in own department |
| Employee | Own department only | Only self |
