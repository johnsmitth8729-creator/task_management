# Security Architecture

## Authentication

Use Django authentication with a custom user model from the start.

Password hashing should use Django's current secure default hashers. Enforce strong password policy through validators.

## Authorization

Use:

- role-based permissions
- object-level permission checks
- department scope checks
- authorized querysets/selectors
- service-layer guards before mutation

Never rely on frontend button hiding for security.

## CSRF

Use Django CSRF protection for all unsafe browser requests.

## XSS

Use Django template autoescaping. Sanitize or strictly render user-supplied rich text if rich text is ever introduced.

## SQL Injection

Use Django ORM and parameterized queries. Avoid raw SQL unless necessary; when used, parameterize safely and review.

## Sessions

Recommended production settings:

- secure cookies over HTTPS
- HTTP-only session cookies
- SameSite protection
- session expiry policy
- login throttling

## File Security

- configurable allowed extensions
- configurable file size limit
- MIME validation
- safe stored filenames
- private storage path
- permission-controlled downloads
- audit file upload/delete
- future antivirus scanning hook

## Rate Limiting

Add rate limiting for:

- login attempts
- password reset attempts
- file uploads
- expensive report generation endpoints

## Audit

Audit important operations:

- task created
- task assigned
- task accepted
- task submitted
- task approved
- task rejected
- deadline changed
- user created
- permission changed
- file uploaded
- file deleted
- settings changed
- payroll viewed or exported where required

## Environment and Secrets

Use environment variables for:

- Django secret key
- database URL/credentials
- Redis URL
- allowed hosts
- email credentials
- storage credentials

Do not commit secrets to Git.

## Deployment Security

Production should use:

- Gunicorn behind Nginx
- HTTPS
- secure headers
- static/media separation
- private media storage
- database backups
- log rotation

## Critical Invariants

- Rector can access everything.
- Vice Rector can act only inside assigned departments.
- Department Head can manage only own department.
- Employee can access only authorized assigned work.
- Department Head and Employee cannot change official deadline.
- First and second approvals are distinct.
- KPI and payroll historical records remain auditable.

