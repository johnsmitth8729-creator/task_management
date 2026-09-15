# Workflow Automation & SLA Engine Architecture (Phase 11)

## 1. Overview
The Workflow Automation module provides an enterprise-grade rule execution engine, SLA compliance monitoring, escalation hierarchy, and recurring task generation for the University Task Management Platform.

## 2. Core Entities
- **`SLAPolicy`**: Defines maximum allowable response and resolution times (in hours) based on task priority or category.
- **`EscalationPolicy`**: Defines automated multi-tier escalation triggers (`DEADLINE_BREACHED`, `SLA_RESPONSE_BREACHED`, `SLA_RESOLUTION_BREACHED`, `INACTIVITY`), target roles (e.g., Vice Rector, Department Head), and corrective actions (`NOTIFY_USER`, `REASSIGN_TASK`, `CHANGE_PRIORITY`, `NOTIFY_AND_REASSIGN`).
- **`RecurringTaskRule`**: Defines cron/frequency templates (Daily, Weekly, Monthly, Semester, Annual) with dynamic title interpolations and automated assignment generation.
- **`AutomationRule`**: Event-driven trigger-condition-action engine supporting triggers (`TASK_CREATED`, `TASK_SUBMITTED`, `TASK_APPROVED`, `DEADLINE_APPROACHING`, `SLA_BREACHED`) with configurable JSON operators and actions (`ASSIGN_USER`, `CHANGE_STATUS`, `SEND_NOTIFICATION`, `ADD_TAG`).
- **`AutomationExecution`**: Comprehensive audit trail capturing rule triggers, evaluation matches, action results, timestamps, and error traces.

## 3. Automation Engine Pipeline
```
[Event Trigger] ──────────► [Rule Matcher] ──────────► [Action Executor] ──────────► [Execution Log]
 (e.g. Task Created)        (Condition Evaluation)       (Notify / Reassign)          (Audit Trail)
```

## 4. Background Scheduler & CLI Commands
The platform includes dedicated management commands for running background jobs via systemd/cron:
- `python manage.py run_automation_scheduler --loop --interval 60`: Runs SLA compliance evaluation, escalation triggering, and recurring task generation every 60 seconds.
- `python manage.py automation_healthcheck`: Validates policy configurations, rule syntax, and scheduler readiness.

## 5. Security & Isolation
- Automation actions respect all RBAC boundaries and organizational department ownership.
- Salary or restricted financial data cannot be queried or leaked via automation triggers.
