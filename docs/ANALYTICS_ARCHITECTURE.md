# Phase 10: Advanced Analytics, Executive Monitoring & Reporting Architecture

## 1. Overview & Objectives
Phase 10 introduces a high-performance, role-scoped analytics and reporting subsystem to the University Task Management Platform. It enables institutional leadership (Rector, Vice Rectors, Department Heads), HR managers, Finance officers, and regular employees to monitor workload dynamics, turnaround speed, bottleneck queues, and deadline compliance in real-time.

Key architectural pillars:
- **Zero Raw SQL Injection Risk & Direct DB Aggregation**: Heavy reliance on Django query annotations (`Count`, `Sum`, `Avg`, `F`, `Q`, `Coalesce`, `TruncDate`) instead of memory-heavy Python loops.
- **Strict Role-Based Scoping & IDOR Prevention**: Queries are bounded by the user's role and departmental scope (`get_scoped_tasks`). Non-superadmin/non-finance users are strictly forbidden from viewing individual salary numbers.
- **Multi-Format Streaming Exports**: Instant generation of branded PDF reports (via ReportLab), formatted Excel workbooks (via openpyxl), and RFC-compliant UTF-8 CSV files.
- **Configurable Executive Thresholds**: Real-time evaluation against institutional warning criteria (overdue task limits, minimum on-time completion rates, average queue wait days).

---

## 2. Core Components

### 2.1 Analytics Data Models (`analytics/models.py`)
1. `AnalyticsThresholdConfig`:
   - Configurable alert thresholds for institutional governance (`max_acceptable_overdue_tasks`, `min_completion_rate_percent`, `min_ontime_rate_percent`, `max_first_approval_wait_days`, etc.).
   - Provides singleton lookup via `AnalyticsThresholdConfig.get_active()`.
2. `SavedReportConfiguration`:
   - Stores saved and system preset report configurations in the Report Center (`UNIVERSITY_TASKS`, `DEPARTMENT_PERFORMANCE`, `KPI_SUMMARY`, `PAYROLL_ANALYTICS`, `SIGNATURE_AUDIT`, `DEADLINE_COMPLIANCE`, `HR_DISTRIBUTION`).

### 2.2 Optimized Selectors (`analytics/selectors.py`)
- `get_scoped_tasks(user, department_id, date_range)`: Core RBAC queryset boundary.
- `get_executive_metrics(user, department_id, date_range)`: University-level completion, on-time rate, turnaround time, overdue rate, and signing rate.
- `get_department_comparison_data(user, date_range)`: Tabular and comparative breakdown per department.
- `get_bottleneck_metrics(user, department_id, date_range)`: Real-time queue volume and average transition durations across approval stages.
- `get_deadline_metrics(user, department_id, date_range)`: Strict deadline breakdown (due today, due tomorrow, due this week, overdue, on-time compliance rate).
- `get_hr_analytics_metrics(user, date_range)`: Headcount, active staff, leave status, position coverage, and grade distribution.
- `get_payroll_analytics_metrics(user, department_id, date_range)`: Institutional compensation totals, gross/net distribution, bonuses, KPI bonuses, and tax deductions (strict RBAC).
- `get_signature_analytics_metrics(user, date_range)`: Electronic signing volumes, revocation rates, and QR verification event statistics.
- `get_employee_personal_metrics(employee, date_range)`: Self-service performance indicators (turnaround days, on-time rate, assigned vs completed).

### 2.3 Visual Chart Generators (`analytics/charts.py`)
Generates structured JSON datasets for Chart.js:
- `get_task_status_chart_data`: Doughnut chart of task statuses.
- `get_task_trends_chart_data`: Line chart comparing task creation vs completion over time.
- `get_bottleneck_radar_chart_data`: Radar chart displaying workflow bottleneck durations.
- `get_department_comparison_chart_data`: Bar chart comparing department performance.
- `get_deadline_compliance_chart_data`: Doughnut chart for deadline adherence.
- `get_signature_trends_chart_data`: Time-series curve of electronic signing activity.

### 2.4 Document & Data Exporters (`analytics/exports.py`)
- `export_pdf_report`: Generates executive PDF reports with university branding, summary tables, metadata headers, and pagination using ReportLab.
- `export_excel_report`: Generates styled XLSX workbooks with header styling, thin borders, column auto-sizing, and formatted summary cards via openpyxl.
- `export_csv_report`: Generates RFC-compliant UTF-8 CSV streams with UTF-8 BOM headers for seamless Excel compatibility.

---

---

## 3. URL Routing & Canonical Routes

| Dashboard / Feature | Canonical URL | Django Named URL | Authorized Roles |
| :--- | :--- | :--- | :--- |
| **Analytics Entrypoint** | `/analytics/` | `analytics:index` | Authenticated (Redirects to `/analytics/executive/`) |
| **Executive Monitoring** | `/analytics/executive/` | `analytics:executive_dashboard` | Rector, Vice Rector (Scoped), Superadmin |
| **Department Analytics** | `/analytics/departments/` | `analytics:department_analytics` | Dept Head (Own), Vice Rector (Scoped), Rector, Superadmin |
| **Personal Performance** | `/analytics/personal/` | `analytics:personal_analytics` | All Authenticated Users (Self-scoped) |
| **HR Workforce Analytics** | `/analytics/hr/` | `analytics:hr_analytics` | HR Manager, Rector, Superadmin |
| **Payroll Financial Analytics** | `/analytics/payroll/` | `analytics:payroll_analytics` | Finance Officer, Rector/Vice Rector/Head (Aggregated) |
| **Signature Analytics** | `/analytics/signatures/` | `analytics:signature_analytics` | Rector, Vice Rector, Superadmin |
| **Security & Audit Analytics** | `/analytics/audit/` | `analytics:audit_analytics` | Superadmin Only |
| **Report Center** | `/analytics/reports/` | `analytics:report_center` | All Authenticated Scoped Roles |
| **Report Export Endpoint** | `/analytics/reports/export/` | `analytics:report_export` | Role-Scoped Export Access |

---

## 4. RBAC Scoping Matrix

| Role | Accessible Dashboards | Scope of Data | Individual Salary Visibility |
| :--- | :--- | :--- | :--- |
| **Superadmin** | Executive, Dept, HR, Payroll, Signature, Security Audit, Report Center | Entire University | Yes (Technical Audit) |
| **Rector** | Executive, Dept, Signature, Report Center | Entire University | **NO** (Aggregate spend only) |
| **Vice Rector** | Executive (Sector), Dept, Signature, Report Center | Supervised Departments | **NO** (Aggregate spend only) |
| **Department Head**| Department Analytics, Signature, Report Center | Own Department Only | **NO** (Aggregate spend only) |
| **HR Manager** | HR Workforce Analytics, Report Center, Personal | University-Wide HR / Personal | **NO** (Per Phase 8 governance) |
| **Finance Officer**| Payroll Analytics, Report Center, Personal | University-Wide Compensation | Yes (Authorized Finance Ops) |
| **Employee** | Personal Performance Analytics | Own Assigned Tasks Only | **NO** (Own Payslips Only) |

---

## 5. Verification & Health Monitoring
The subsystem includes a dedicated management command:
```bash
python manage.py analytics_healthcheck
```
It validates:
1. Task timestamp ordering consistency (`completed_at >= created_at`).
2. Absence of missing completion timestamps on completed tasks.
3. Foreign key integrity across task assignments.
4. Cryptographic signature and verification log relationships.
5. Active threshold configuration loading.
