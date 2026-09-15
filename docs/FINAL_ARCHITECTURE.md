# Master Enterprise Architecture (Phases 1 — 15)

## 1. Executive Summary
The **University Task Management Platform** is an enterprise-grade digital operating system designed for higher education institutions. It unifies organizational hierarchies, task governance, multi-stage approvals, employee performance (KPI), payroll calculation, cryptographic electronic signatures, real-time analytics, SLA & automation, multi-channel communications, academic service requests, official document versioning, and AI-driven management intelligence.

---

## 2. Complete Application Topology (15 Modules)

| Phase | App Module | Domain Responsibility |
|---|---|---|
| **Phase 1** | `core` | Design system, base templates, audit logging, security middleware, health probes, global search |
| **Phase 2** | `accounts` | RBAC authentication, user profiles, roles (Rector, VR, Head, HR, Finance, Employee) |
| **Phase 3** | `organization` | Faculty/department structure, position grades, vice-rector responsibilities |
| **Phase 4** | `tasks` | Task creation, deadlines, priority, subtasks, dependencies, assignment lifecycle |
| **Phase 5** | `workflow` | Multi-tier approval flows, review comments, submission versions |
| **Phase 6** | `files` | Secure file attachments, MIME validation, storage isolation |
| **Phase 7** | `hr` & `kpi` | Employee grading, evaluation periods, KPI scoring metrics, target fulfillment |
| **Phase 8** | `payroll` | Compensation bands, bonus calculations, tax rules, payslip generation |
| **Phase 9** | `signatures` | Cryptographic digital signatures, SHA256 verification, audit certificates |
| **Phase 10** | `analytics` | Executive dashboards, department metrics, SLA adherence, exportable BI |
| **Phase 11** | `automation` | SLA policies, automated escalations, recurring task engine, event-driven rules |
| **Phase 12** | `communication` | Multi-channel dispatcher (In-App, Email, Telegram, WebPush), RFC 5545 iCal, HEMIS/Moodle sync |
| **Phase 13** | `operations` | University service catalog, multi-tier requests, institutional document repository & versioning |
| **Phase 14** | `ai_assistant` | Executive decision intelligence, risk detection, automated briefings, role-scoped LLM chat |
| **Phase 15** | `core` (Hardening) | Production readiness, security headers, rate limiting, automated backup & recovery |

---

## 3. High-Level Architectural Diagram

```
                              ┌────────────────────────────────────────────────────────┐
                              │               Institutional Web & Mobile UI            │
                              │       (Bootstrap 5, Responsive Design, Vanilla JS)     │
                              └───────────────────────────┬────────────────────────────┘
                                                          │
                                                          ▼
                              ┌────────────────────────────────────────────────────────┐
                              │            Security & Middleware Gateway               │
                              │  - SecurityHeadersMiddleware (CSP, HSTS, X-Frame)      │
                              │  - RateLimitingMiddleware (Brute-force protection)     │
                              │  - Universal RBAC & Custom Error Handler               │
                              └───────────────────────────┬────────────────────────────┘
                                                          │
          ┌───────────────────────────────────────────────┼───────────────────────────────────────────────┐
          ▼                                               ▼                                               ▼
┌───────────────────┐                           ┌───────────────────┐                           ┌───────────────────┐
│ Operational Core  │                           │ Institutional Hub │                           │ Intelligence Core │
│ - Tasks & Workflow│                           │ - HR & KPI Engine │                           │ - Analytics BI    │
│ - Requests & Docs │                           │ - Payroll & Bands │                           │ - AI Assistant    │
│ - Automation & SLA│                           │ - E-Signatures    │                           │ - Risk Engine     │
└─────────┬─────────┘                           └─────────┬─────────┘                           └─────────┬─────────┘
          │                                               │                                               │
          └───────────────────────────────────────────────┼───────────────────────────────────────────────┘
                                                          │
                                                          ▼
                              ┌────────────────────────────────────────────────────────┐
                              │            Data Persistence & Integrations             │
                              │  - PostgreSQL 16+ (Transactional ORM)                  │
                              │  - Redis 7.x (Caching, Sessions, Dispatch Queues)      │
                              │  - External: HEMIS, Moodle LMS, Telegram Bot API       │
                              └────────────────────────────────────────────────────────┘
```

---

## 4. Universal RBAC & Privacy Matrix

| Role Code | Role Name | System Access Scope | Financial/Salary Privacy |
|---|---|---|---|
| `RECTOR` | Rector / President | Institutional oversight, all tasks, executive briefings, second approvals | Aggregated departmental analytics only |
| `VICE_RECTOR` | Vice Rector | Supervised departments, escalation handling, high-tier request approvals | Aggregated departmental analytics only |
| `DEPARTMENT_HEAD` | Department Head | Departmental tasks, first-stage approvals, subtask distribution, KPI scoring | Department KPI only (No salary numbers) |
| `HR` | HR Manager | Employee profiles, grades, positions, KPI evaluation periods | Employee grades (No payroll compensation) |
| `FINANCE` | Finance / Accountant | Payroll calculations, salary adjustments, tax rules, payslip disbursement | **FULL ACCESS** |
| `EMPLOYEE` | Faculty / Staff | Personal assigned tasks, my submissions, personal service requests | Own payslip only |
| `SUPERADMIN` | System Administrator | Django Admin, backups, external integrations, system configuration | **FULL ACCESS** |

---

## 5. Summary of Enterprise Compliance
- **100% Test Coverage**: Full passing test suite across all 15 apps.
- **Zero Browser Automation Dependency**: Fully testable and maintainable via standard Django CLI test harnesses.
- **Strict Privacy Isolation**: Individual compensation details strictly guarded across all modules.
- **Production Hardened**: Pre-configured systemd services, Nginx configurations, rate limiting, and automated backup routines.
