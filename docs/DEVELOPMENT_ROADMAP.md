# Development Roadmap

This roadmap is frozen. Do not create additional major phases.

Bug fixing and correction must happen inside the current phase.

## PHASE 0 - Blueprint & Architecture

Deliver architecture and planning documentation only.

No application implementation.

## PHASE 1 - Foundation & Authentication

Create Django project foundation, configuration, environment handling, PostgreSQL connection, custom user model, authentication foundation, language configuration, and base templates.

## PHASE 2 - Organization, Users & RBAC / Admin

Implement university organization structure, departments, positions, user roles, Vice Rector department scopes, Department Head assignment, and backend RBAC policies.

## PHASE 3 - Complete Task Engine

Implement core task models, task types, priorities, complexity, assignments, lifecycle state storage, and service-layer transition foundations.

## PHASE 4 - Employee & Department Workflow

Implement Department Head assignment workflow, employee acceptance, progress updates, employee task views, department task views, and scoped access enforcement.

## PHASE 5 - Approval, Rejection & Completion

Implement two-level approval workflow, first approval, final approval, rejection reasons, completion rules, and full audit/history recording.

## PHASE 6 - Notifications, Deadlines & Escalation

Implement database notifications, read/unread, deadline reminders, overdue detection, deadline changes, and escalation foundation.

## PHASE 7 - Files, Notes, History, Search & Reports

Implement secure files, notes, comments, task history timeline, search/filtering, and report generation foundations.

## PHASE 8 - Analytics, Workload & Performance

Implement analytics dashboards, department/employee performance metrics, workload calculation foundation, and Chart.js views.

## PHASE 9 - KPI, Payroll & Final Production

Implement configurable KPI rules, KPI snapshots, payroll/bonus calculation foundation, production settings, Gunicorn/Nginx deployment documentation, and final hardening.

## AI Development Rule

Each phase follows:

Agent Prompt -> Implementation -> Agent stops -> Local testing -> Correction if necessary -> Retest -> Git commit -> Next phase

Do not automatically implement the next phase.

