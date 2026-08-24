# API Architecture

## Approach

Use Django views/templates for the primary internal UI. Use Django REST Framework where API functionality is appropriate.

Good API candidates:

- dynamic task filters
- notifications read/unread
- chart data
- file download authorization endpoints
- report generation requests
- future integrations

## API Versioning

Use a versioned API namespace when public or integration-facing endpoints are introduced:

- `/api/v1/tasks/`
- `/api/v1/notifications/`
- `/api/v1/analytics/`

Internal AJAX endpoints may live under normal app URLs if they are tightly coupled to server-rendered pages.

## Authorization

Every API endpoint must use:

- authentication
- role checks
- object-level permission checks
- scoped querysets

List endpoints must return only objects visible to the user.

Detail endpoints must fetch from authorized querysets.

Mutation endpoints must call domain services rather than updating models directly in serializers/views.

## Suggested URL Structure

Browser URLs:

- `/login/`
- `/dashboard/`
- `/tasks/`
- `/tasks/<id>/`
- `/tasks/create/`
- `/tasks/<id>/assign/`
- `/tasks/<id>/accept/`
- `/tasks/<id>/submit/`
- `/tasks/<id>/approve/`
- `/tasks/<id>/reject/`
- `/notifications/`
- `/users/`
- `/departments/`
- `/reports/`
- `/analytics/`
- `/kpi/`
- `/payroll/`
- `/settings/`

API URLs:

- `/api/v1/tasks/`
- `/api/v1/tasks/<id>/`
- `/api/v1/tasks/<id>/assignments/`
- `/api/v1/tasks/<id>/submissions/`
- `/api/v1/tasks/<id>/approvals/`
- `/api/v1/notifications/`
- `/api/v1/reports/`
- `/api/v1/analytics/`

## Serialization

Serializers should expose codes for statuses/roles and translated labels separately when needed:

- `status`: `IN_PROGRESS`
- `status_label`: translated display string

Do not use translated labels as API inputs for business logic.

