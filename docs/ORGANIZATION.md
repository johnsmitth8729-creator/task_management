# Organization Architecture

## Hierarchy

University → Rector → Vice Rectors → Departments → Department Heads → Positions → Employees

## Core Models (Phase 2 — Implemented)

### Department (`organization.Department`)

Operational task unit. Every task must belong to one department.

Fields:
- `id` — UUID primary key
- `name` — full department name
- `code` — short code (unique, e.g. `IT`, `FIN`)
- `description` — optional text description
- `head` — ForeignKey to `User` (nullable; the assigned Department Head)
- `is_active` — soft-delete flag
- `created_at`, `updated_at` — audit timestamps

### Position (`organization.Position`)

Employee job position. A position may be global or department-specific.

Fields:
- `id` — UUID primary key
- `name` — full position title
- `code` — short code (unique, e.g. `DEV`, `HR_OFFICER`)
- `description` — optional text description
- `department` — ForeignKey to `Department` (nullable; department-specific positions)
- `is_active` — soft-delete flag
- `created_at`, `updated_at` — audit timestamps

### DepartmentResponsibility (`organization.DepartmentResponsibility`)

Maps a Vice Rector to one or more departments.

This model is the primary enforcement point for Vice Rector scope.

Fields:
- `id` — UUID primary key
- `vice_rector` — ForeignKey to `User`
- `department` — ForeignKey to `Department`
- `start_date` — date the responsibility began
- `end_date` — date the responsibility ended (nullable)
- `is_active` — current active flag
- `created_at`, `updated_at` — audit timestamps

Constraints:
- `UniqueConstraint` on `(vice_rector, department)` where `is_active=True` — prevents duplicate active responsibilities

## Role Placement

### Rector
- Global university authority (superuser).
- `User.is_rector` property checks for `RECTOR` role or Django superuser.

### Vice Rector
- User with `VICE_RECTOR` role.
- One or more active `DepartmentResponsibility` rows.
- `User.get_scoped_departments()` returns only assigned departments.
- `User.get_scoped_users()` returns users belonging to those departments.

### Department Head
- User with `DEPARTMENT_HEAD` role.
- The `Department.head` FK references this user.
- `User.get_scoped_departments()` returns `Department.objects.filter(id=self.department_id)`.
- `User.get_scoped_users()` returns users in the same department.

### Employee
- User with `EMPLOYEE` role.
- One department, one position.
- `User.get_scoped_departments()` returns only own department.
- `User.get_scoped_users()` returns only self.

## Services (`organization.services`)

All organizational mutations are done through service functions to ensure audit logging:

- `assign_department_head(department, user, actor)` — sets `department.head` and logs the action.
- `assign_vice_rector_responsibility(vice_rector, department, actor)` — creates `DepartmentResponsibility` and logs.
- `remove_vice_rector_responsibility(responsibility, actor)` — deactivates a responsibility and logs.

## Historical Responsibility

Responsibility rows use effective dates:
- `start_date`
- `end_date` (nullable)
- `is_active`

This preserves historical reporting and auditability. Old rows are never deleted, only deactivated.

## Expansion Support

The architecture supports:
- multiple organizational unit levels (future `OrganizationalUnit` tree)
- department renaming without losing history
- inactive departments (soft-delete via `is_active`)
- position changes over time
- temporary acting department heads (change `Department.head`)
- Vice Rector responsibility changes over time via `DepartmentResponsibility`



## Future Expansion

- `OrganizationalUnit` tree for faculties, centers, and branches
- `University` model for global identity and branding settings
- `EmployeeProfile` for richer employment history tracking
