# Architecture

## System Style

TASK MANAGEMENT will be a Django monolith with clear domain apps. This is the right first architecture because the product needs strong relational consistency, strict authorization, auditable workflows, and server-rendered Bootstrap pages with selected API endpoints.

The application should use:

- Django views/templates for primary internal UI.
- Django REST Framework for endpoints needed by dynamic UI, integrations, exports, or future mobile clients.
- Django ORM with PostgreSQL.
- Celery and Redis for asynchronous jobs such as reminders, deadline checks, report generation, notification dispatch, KPI snapshots, and payroll calculations.

## Proposed Django Apps

### `core`

Shared infrastructure:

- base timestamped models
- soft-delete/archive helpers where appropriate
- system settings access
- i18n helpers
- audit helper API
- common exceptions
- common validators

### `accounts`

Identity and role membership:

- custom user model
- roles
- permission groups
- user profile fields
- authentication integration
- user status and security flags

### `organization`

University structure:

- university
- organizational units
- departments
- positions
- employee department membership
- department head assignment
- Vice Rector department responsibility scopes

### `tasks`

Task domain data:

- tasks
- task types
- priorities and complexity
- task assignments
- submissions
- attachments
- comments and notes
- deadline changes
- task history
- templates, recurring tasks, subtasks, dependencies as future-ready models

### `workflow`

State and approval rules:

- transition service
- permission policy checks for transitions
- approval orchestration
- rejection handling
- lifecycle guards

Workflow logic should live in services, not views or templates.

### `notifications`

Notification storage and dispatch:

- notification model
- notification type
- read/unread state
- related object references
- dispatch queue hooks
- future WebSocket/Channels integration boundary

### `files`

Secure file handling:

- allowed extension settings
- size limits
- storage metadata
- content validation
- permission-controlled download views
- future antivirus scanning hook

### `analytics`

Read/query architecture:

- dashboard query services
- aggregate models or materialized views where needed
- analytics permissions
- workload and performance metrics

### `kpi`

Configurable KPI engine:

- KPI rule definitions
- rule weights
- KPI periods
- KPI snapshots
- task-derived KPI inputs
- manager evaluation input placeholders

### `payroll`

Restricted payroll/bonus engine:

- salary records
- payroll rules
- salary adjustments
- payroll period snapshots
- access policy for confidential salary data

### `reports`

Report generation:

- report request records
- generated report files
- PDF/DOCX/XLSX/CSV generation jobs
- report permission policy

## Layering

Recommended layering inside apps:

- `models.py`: persistence and simple invariants.
- `services.py`: business operations and state changes.
- `permissions.py`: role, object, and scope checks.
- `selectors.py`: authorized querysets/read operations.
- `forms.py`: server-rendered forms.
- `serializers.py`: DRF serializers where APIs are required.
- `views.py`: HTTP orchestration only.
- `tasks.py`: Celery jobs.
- `tests/`: unit and integration tests.

## Internationalization

Use Django i18n:

- `LANGUAGES = [('uz', ...), ('en', ...), ('ru', ...)]`
- `LocaleMiddleware`
- `{% trans %}` and `{% blocktrans %}` in templates
- `gettext_lazy` for model labels, forms, choices, and validation messages
- language-neutral enum/database codes

Do not use translated strings as state identifiers, role identifiers, permission identifiers, or business-rule inputs.

## Background Jobs

Celery jobs should later handle:

- deadline warning generation
- overdue detection
- escalation notifications
- report generation
- KPI snapshot calculation
- payroll snapshot calculation
- cleanup of expired temporary files

## Real-Time Future Boundary

The notification app should be designed so database notifications work first. Later, Django Channels can broadcast notification events to WebSocket clients without changing task/workflow business logic.

