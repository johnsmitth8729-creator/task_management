# Project Overview

## Mission

TASK MANAGEMENT is a university-wide internal platform for task management, workflow, monitoring, approvals, KPI, and KPI-based payroll/bonus calculation.

The system must provide a controlled digital workflow from executive task creation through department execution, two-level approval, analytics, KPI snapshots, and later payroll/bonus calculation.

## Phase Boundary

This document belongs to **Phase 0: Blueprint & Architecture**.

Phase 0 creates documentation only. It does not implement:

- Django project scaffolding
- authentication UI
- dashboards
- task CRUD
- notifications
- KPI calculations
- payroll calculations
- reports
- production deployment

## Required Languages

The final product supports exactly:

- Uzbek
- English
- Russian

All user-facing text must be translatable through Django internationalization. Business logic must not depend on display text.

## Core Roles

- Rector / Superadmin
- Vice Rector / Admin
- Department Head
- Employee / User

## Core Workflow

1. Rector creates a task for any department, or Vice Rector creates a task only for departments assigned to that Vice Rector.
2. Department receives the task.
3. Department Head assigns employee(s).
4. Employee accepts the task.
5. Employee works, adds notes/files, and submits result.
6. Department Head performs first approval or rejection.
7. Rector or responsible Vice Rector performs final approval or rejection.
8. Completed task contributes to monitoring, analytics, KPI, and later payroll/bonus calculation.

## Design Principles

- Backend authorization is mandatory for every sensitive operation.
- Object-level permission checks are required.
- Department scope must be enforced in querysets and service-layer policy checks.
- Workflows must be represented by explicit states and validated transitions.
- Historical data must be preserved through audit logs and history tables.
- KPI and payroll formulas must be configurable, not hardcoded.
- File access must be permission controlled.
- Architecture must support future expansion: more departments, roles, task types, templates, recurring tasks, subtasks, dependencies, workload, calendar, Kanban, escalation, and real-time notifications.

