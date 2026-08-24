# Organization Architecture

## Hierarchy

University -> Rector -> Vice Rectors -> Departments -> Department Heads -> Positions -> Employees

The database should also support a generalized `OrganizationalUnit` tree for future expansion.

## Core Models

### University

Represents the institution and stores global identity settings such as name, logo, timezone, and active status.

### OrganizationalUnit

Generic hierarchical model for future expansion beyond departments.

Examples:

- faculty
- center
- office
- department
- branch

### Department

Operational task unit. Every task must belong to one department.

### Position

Employee job position. A position may be global or department-specific.

### EmployeeProfile

Connects a user to:

- department
- position
- employment status
- manager relationship if needed

### DepartmentResponsibility

Maps a Vice Rector to one or more departments.

This model is the primary enforcement point for Vice Rector scope.

## Role Placement

Rector:

- global university authority

Vice Rector:

- user with `VICE_RECTOR` role
- one or more active `DepartmentResponsibility` rows

Department Head:

- user with `DEPARTMENT_HEAD` role
- exactly one primary department unless future rules allow multiple

Employee:

- user with `EMPLOYEE` role
- one department
- one position

## Expansion Support

The architecture should support:

- multiple organizational unit levels
- department renaming without losing history
- inactive departments
- position changes over time
- future branch campuses
- temporary acting department heads
- Vice Rector responsibility changes over time

## Historical Responsibility

Responsibility tables should use effective dates:

- `start_date`
- `end_date`
- `is_active`

This preserves historical reporting and auditability.

