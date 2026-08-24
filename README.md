# TASK MANAGEMENT

TASK MANAGEMENT is a university-wide internal platform for task management, workflow monitoring, approvals, analytics, KPI, and configurable payroll/bonus calculation.

This repository is currently in **Phase 2: Organization, Users & RBAC / Admin**. The organizational hierarchy, department and position management, user management, Vice Rector department responsibilities, Department Head assignments, object-level & department-scoped RBAC, audit logging, role-based navigation, and university-branded UI are fully implemented and verified.

## Purpose

The platform digitizes the university task lifecycle:

Rector or Vice Rector creates a task -> Department receives it -> Department Head assigns employee(s) -> Employee accepts and works on it -> Employee submits result/report/files -> Department Head performs first approval -> Rector or responsible Vice Rector performs final approval -> Task contributes to monitoring, analytics, KPI, and later configurable bonus/salary calculation.

## Technology Stack

Backend:
- Python (3.12+)
- Django (6.1+)
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

The application supports:

- Uzbek (`uz`)
- English (`en`)
- Russian (`ru`)

Django internationalization is used across views, forms, and templates with language switcher support.

## Development Phases

The roadmap is frozen:

- [x] **Phase 0: Blueprint & Architecture**
- [x] **Phase 1: Foundation & Authentication**
- [x] **Phase 2: Organization, Users & RBAC / Admin**
- [ ] Phase 3: Complete Task Engine
- [ ] Phase 4: Employee & Department Workflow
- [ ] Phase 5: Approval, Rejection & Completion
- [ ] Phase 6: Notifications, Deadlines & Escalation
- [ ] Phase 7: Files, Notes, History, Search & Reports
- [ ] Phase 8: Analytics, Workload & Performance
- [ ] Phase 9: KPI, Payroll & Final Production

Future development proceeds phase by phase.

---

## Local Development Setup

### 1. Prerequisites
- Python 3.12+
- PostgreSQL 14+
- Git

### 2. Environment Setup

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment (Windows PowerShell)
.venv\Scripts\Activate.ps1
# Or on Linux / macOS:
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Variables

Create `.env` from `.env.example`:

```bash
cp .env.example .env
```

Configure your PostgreSQL database credentials in `.env`:
```env
SECRET_KEY=your-secret-key-for-development
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=task_management
DB_USER=postgres
DB_PASSWORD=your_postgres_password
DB_HOST=localhost
DB_PORT=5432

TIME_ZONE=Asia/Tashkent
LANGUAGE_CODE=en
```

### 4. Database Migrations

Apply migrations to your PostgreSQL database:

```bash
python manage.py makemigrations
python manage.py migrate
```

### 5. Seed Development Data

Populate initial test roles, departments, positions, responsibilities, and accounts:

```bash
python manage.py seed_dev
```

This creates the following development accounts (Password: `ChangeMe12345!`):
- **Rector**: `rector` (Superadmin, global authority)
- **Vice Rector Academic**: `vice.rector` (Supervises IT & Library)
- **Vice Rector Finance**: `vice.rector.finance` (Supervises Finance & HR)
- **Department Head IT**: `department.head` (Head of IT Department)
- **Department Head Library**: `head.library` (Head of University Library)
- **Department Head Finance**: `head.finance` (Head of Finance & Accounting)
- **Employee IT**: `employee.one` (Senior Software Engineer / IT)
- **Employee Library**: `employee.two` (Librarian / Library)
- **Employee Finance**: `employee.finance` (Senior Accountant / Finance)

### 6. Run Automated Tests

```bash
python manage.py test
```

### 7. Start Development Server

```bash
python manage.py runserver
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser.

