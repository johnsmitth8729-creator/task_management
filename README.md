# TASK MANAGEMENT

TASK MANAGEMENT is a university-wide internal platform for task management, workflow monitoring, approvals, analytics, KPI, and configurable payroll/bonus calculation.

This repository is currently in **Phase 10: Advanced Analytics, Executive Monitoring & Reporting**. The platform features enterprise-grade aggregated analytics: real-time executive dashboards, department comparative matrices, workflow bottleneck duration detection, strict deadline compliance tracking, Report Center with saved report presets, multi-format streaming exports (ReportLab PDF, openpyxl Excel, RFC-compliant UTF-8 CSV), interactive Chart.js visualization, and subsystem health check diagnostics.

## Purpose

The platform digitizes the university task lifecycle:

Rector or Vice Rector creates a task -> Department receives it -> Department Head assigns employee(s) -> Employee accepts and works on it -> Employee submits result/report/files -> Department Head performs first approval -> Rector or responsible Vice Rector performs final approval -> Task is cryptographically signed with an Ed25519 electronic signature and QR verification seal -> Task contributes to monitoring, analytics, KPI, and configurable payroll/bonus calculation.

---

## Main Roles

- **Technical Superadmin** (System administration, user roles, technical audit logs, security analytics, signature administrative authority)
- **Rector** (Global operational authority, executive analytics, aggregated KPI & payroll metrics, final deliverable approvals, university-wide electronic signature authority)
- **Vice Rector** (Scoped to assigned departments, sector analytics, aggregated department metrics, stage 2 approvals, scoped electronic signature authority)
- **Department Head** (Scoped to own department, departmental analytics, first approvals, aggregated department metrics)
- **Finance Officer** (Operational payroll execution, salary configurations, payroll analytics, adjustment approvals, disbursements)
- **HR Manager** (Personnel management, grade and organizational assignments, workforce analytics)
- **Employee** (Assigned tasks execution, self-service performance analytics, salary profile, payslips, and personal payroll records)

Authorization is enforced strictly on the backend. Frontend visibility is only a usability feature and is never considered security.

---

## Development Phases

- [x] **Phase 0: Blueprint & Architecture**
- [x] **Phase 1: Foundation & Authentication**
- [x] **Phase 2: Organization, Users & RBAC / Admin**
- [x] **Phase 3: Complete Task Engine**
- [x] **Phase 4: Employee & Department Workflow**
- [x] **Phase 5: Approval, Rejection & Completion**
- [x] **Phase 6: Files, Reports, Documents & Submission System**
- [x] **Phase 7: HR Hierarchy, Organizational Structure & Granular Delegation**
- [x] **Phase 8: Payroll & Compensation Engine with Strict Role Governance & Privacy**
- [x] **Phase 9: Electronic Signature, QR Verification & Cryptographic Task Signing**
- [x] **Phase 10: Advanced Analytics, Executive Monitoring & Reporting**


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

Populate initial test roles, departments, positions, responsibilities, accounts, task types, templates, and tasks:

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

### 8. Analytics & Report Center Routes (Phase 10)

- **Executive Monitoring**: `http://127.0.0.1:8000/analytics/executive/` (or `/analytics/` redirect)
- **Department Analytics**: `http://127.0.0.1:8000/analytics/departments/`
- **Personal Performance**: `http://127.0.0.1:8000/analytics/personal/`
- **HR Workforce Analytics**: `http://127.0.0.1:8000/analytics/hr/`
- **Payroll Financial Analytics**: `http://127.0.0.1:8000/analytics/payroll/`
- **Signature Analytics**: `http://127.0.0.1:8000/analytics/signatures/`
- **Security Audit Analytics**: `http://127.0.0.1:8000/analytics/audit/`
- **Report Center**: `http://127.0.0.1:8000/analytics/reports/`

