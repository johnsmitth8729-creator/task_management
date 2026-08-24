# TASK MANAGEMENT

TASK MANAGEMENT is a university-wide internal platform for task management, workflow monitoring, approvals, analytics, KPI, and configurable payroll/bonus calculation.

This repository is currently in **Phase 0: Blueprint & Architecture**. No application implementation, dashboards, task CRUD, notifications, KPI calculation, payroll calculation, reporting, or production deployment is included yet.

## Purpose

The platform digitizes the university task lifecycle:

Rector or Vice Rector creates a task -> Department receives it -> Department Head assigns employee(s) -> Employee accepts and works on it -> Employee submits result/report/files -> Department Head performs first approval -> Rector or responsible Vice Rector performs final approval -> Task contributes to monitoring, analytics, KPI, and later configurable bonus/salary calculation.

## Technology Stack

Backend:
- Python
- Django
- Django ORM
- Django REST Framework where API functionality is appropriate

Frontend:
- HTML5
- CSS3
- JavaScript
- Bootstrap 5
- Bootstrap Icons
- Chart.js where required

Database:
- PostgreSQL

Background processing:
- Celery
- Redis

Production:
- Gunicorn
- Nginx

Development:
- Git
- GitHub
- Google Antigravity Pro
- Antigravity IDE

Node.js is not required.

## Main Roles

- Rector / Superadmin
- Vice Rector / Admin
- Department Head
- Employee / User

Authorization must be enforced on the backend. Frontend visibility is only a usability feature and is never considered security.

## Main Workflow

1. Rector or scoped Vice Rector creates and assigns a task to a department.
2. Department Head receives the task and assigns one or more responsible employees.
3. Employee accepts the task and works on it.
4. Employee uploads result files and submits for first approval.
5. Department Head approves or rejects with a reason.
6. Approved work moves to second approval.
7. Rector or responsible Vice Rector approves or rejects.
8. Completed task data becomes available for analytics, KPI, and later payroll/bonus calculation.

## Project Architecture

The proposed Django domains are:

- `core`: shared settings, base models, i18n utilities, audit helpers.
- `accounts`: users, roles, authentication-facing profile data.
- `organization`: university hierarchy, departments, positions, Vice Rector scopes.
- `tasks`: task records, assignments, submissions, comments, deadlines, attachments.
- `workflow`: task state transitions and approval policy services.
- `notifications`: notification models and dispatch architecture.
- `files`: secure file validation, storage metadata, permission-controlled downloads.
- `analytics`: query/read-model architecture for dashboards and reports.
- `kpi`: configurable KPI rules, snapshots, and scoring inputs.
- `payroll`: payroll configuration and restricted salary/bonus records.
- `reports`: PDF, DOCX, Excel, and CSV report generation architecture.

See `docs/ARCHITECTURE.md` for details.

## Languages

The final application must support exactly:

- Uzbek
- English
- Russian

Django internationalization must be used. UI and system messages must use translation keys instead of hardcoded text in templates or business logic.

## Development Phases

The roadmap is frozen:

- Phase 0: Blueprint & Architecture
- Phase 1: Foundation & Authentication
- Phase 2: Organization, Users & RBAC / Admin
- Phase 3: Complete Task Engine
- Phase 4: Employee & Department Workflow
- Phase 5: Approval, Rejection & Completion
- Phase 6: Notifications, Deadlines & Escalation
- Phase 7: Files, Notes, History, Search & Reports
- Phase 8: Analytics, Workload & Performance
- Phase 9: KPI, Payroll & Final Production

Future development must proceed phase by phase. Do not automatically implement the next phase.

## Local Development Prerequisites

Expected tools for later implementation phases:

- Python 3.12 or current project-approved Python version
- PostgreSQL
- Redis
- Git
- Virtual environment tooling
- Google Antigravity Pro / Antigravity IDE

No Django project has been created in Phase 0.

