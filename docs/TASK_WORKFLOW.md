# Task Workflow

## Main Statuses

Primary lifecycle:

`CREATED` -> `ASSIGNED` -> `RECEIVED` -> `IN_PROGRESS` -> `FIRST_APPROVAL_PENDING` -> `FIRST_APPROVED` -> `SECOND_APPROVAL_PENDING` -> `COMPLETED`

Additional statuses:

- `REJECTED_BY_HEAD`
- `REJECTED_BY_ADMIN`
- `OVERDUE`
- `CANCELLED`
- `ARCHIVED`

Status codes must be stored as stable English-like identifiers and translated only for display.

## Transition Rules

| Transition | Actor | Conditions | Database Changes | Notification | Audit |
|---|---|---|---|---|---|
| create task -> `CREATED` | Rector, scoped Vice Rector | creator can assign target department | create Task | optional draft notification | `TASK_CREATED` |
| `CREATED` -> `ASSIGNED` | Rector, scoped Vice Rector | department is valid and in actor scope | set department, deadline, status | notify Department Head | `TASK_ASSIGNED` |
| `ASSIGNED` -> `RECEIVED` | Department Head | task belongs to own department | mark received timestamp/status | notify creator/admin | `TASK_RECEIVED` |
| assign employee(s) | Department Head, Rector, scoped Vice Rector | employees belong to task department | create `TaskAssignment` rows | notify employees | `TASK_EMPLOYEE_ASSIGNED` |
| `RECEIVED` -> `IN_PROGRESS` | assigned Employee | user has active assignment | set assignment accepted_at, task status if first acceptance | notify Department Head | `TASK_ACCEPTED` |
| progress update | assigned Employee | active assignment and task not final | update progress, optional history | optional notify manager | `TASK_PROGRESS_UPDATED` |
| `IN_PROGRESS` -> `FIRST_APPROVAL_PENDING` | assigned Employee | required submission data/files present if configured | create `TaskSubmission`, set status | notify Department Head | `TASK_SUBMITTED` |
| `FIRST_APPROVAL_PENDING` -> `FIRST_APPROVED` | Department Head | own department, not approver's own submission unless allowed | create level 1 approval | notify final approver(s) | `TASK_FIRST_APPROVED` |
| `FIRST_APPROVED` -> `SECOND_APPROVAL_PENDING` | system/service | first approval exists | set status | notify Rector/responsible Vice Rector | `TASK_SECOND_APPROVAL_PENDING` |
| `SECOND_APPROVAL_PENDING` -> `COMPLETED` | Rector, responsible Vice Rector | valid level 1 approval, actor has final approval scope | create level 2 approval, set completed status/time | notify employee and Department Head | `TASK_COMPLETED` |
| `FIRST_APPROVAL_PENDING` -> `REJECTED_BY_HEAD` | Department Head | own department, reason required | create rejection/approval decision, set status | notify employee | `TASK_REJECTED` |
| `SECOND_APPROVAL_PENDING` -> `REJECTED_BY_ADMIN` | Rector, responsible Vice Rector | actor has final approval scope, reason required | create rejection/approval decision, set status | notify Department Head and employee | `TASK_REJECTED` |
| rejected -> `IN_PROGRESS` | assigned Employee | rejection exists and task is not cancelled | create new work cycle/history event | notify Department Head | `TASK_REWORK_STARTED` |
| any active -> `OVERDUE` | system job | current time past deadline and not completed/cancelled/archived | set overdue marker or status flag | notify assigned users/managers | `TASK_OVERDUE` |
| active -> `CANCELLED` | Rector, scoped Vice Rector | reason required, actor has scope | set cancelled status/timestamp | notify participants | `TASK_CANCELLED` |
| final/cancelled -> `ARCHIVED` | Rector, scoped Vice Rector | archival policy met | set archived status/timestamp | optional | `TASK_ARCHIVED` |

## Status Design Note

`OVERDUE` may be implemented as a derived flag instead of a destructive lifecycle status, because a task can be both `IN_PROGRESS` and overdue. Recommended approach:

- keep `status` for workflow state
- expose `is_overdue` as derived property or separate boolean/timestamp
- create audit/history event when overdue is first detected

## Approval Separation

Level 1:

- Employee -> Department Head
- Department Head approves or rejects
- rejection requires reason

Level 2:

- Department Head approved -> Rector or responsible Vice Rector
- final approver approves or rejects
- rejection requires reason

Store approval level explicitly in `TaskApproval`.

## Deadline Control

Only Rector and responsible Vice Rector can change official task deadline.

Department Head and Employee cannot change official deadline. They may request extension if this feature is enabled later, but official change still requires Rector or responsible Vice Rector approval.

## History Requirements

Every transition must create:

- `TaskHistory` event for visible timeline
- `AuditLog` event for security/audit trail

Task history is user-facing. Audit log is administrative and security-focused.

