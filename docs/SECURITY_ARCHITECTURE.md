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

## File Security (Phase 6)

- Strict extension whitelisting (`ALLOWED_FILE_EXTENSIONS`)
- Rejection of executable scripts (`DISALLOWED_FILE_EXTENSIONS`: `exe`, `bat`, `cmd`, `ps1`, `sh`, `dll`, `scr`, `vbs`, `js`, `jar`, etc.)
- Strict detection of double extensions (`file.exe.pdf`)
- Configurable file size limits (`MAX_FILE_SIZE_MB=50`, `MAX_VIDEO_SIZE_MB=200`)
- Sanitization of user-provided filenames (`sanitize_filename`) stripping path traversal (`..`, `/`, `\`) and null bytes (`\x00`)
- Randomized, collision-resistant storage path (`task_files/<task_id>/<year>/<month>/<uuid>.<ext>`)
- Zero direct public URL exposure for private task files
- Server-side permission-controlled streaming for downloads (`/files/<uuid>/download/`) and inline previews (`/files/<uuid>/view/`)
- Soft deletion with full audit tracking (`deleted_at`, `deleted_by`)
- Integrity verification using SHA-256 checksums

## Django Admin Security Policy (Phase 6)

- Operational roles (Rector, Vice Rector, Department Head, Employee, Finance) are decoupled from Django `is_staff` / `is_superuser` flags.
- Dedicated `superadmin` account (`is_staff=True, is_superuser=True`) is reserved exclusively for technical administrators.
- Operational Rector manages the university via the task management interface with operational authority, NOT through Django Admin.

## Payroll & Role Governance Security (Phase 8)

- **Strict Salary Privacy**: Individual employee compensation records are private to the individual employee and authorized Finance officers.
- **Leadership Scope Restriction**: Rector, Vice Rectors, and Department Heads can only access aggregated compensation summaries; attempts to access individual subordinate records return `403 Forbidden`.
- **IDOR Protection**: All payroll detail views, PDF downloads, and Excel exports perform strict object-level authorization (`can_view_payroll_record(user, record)`). Non-authorized users receive `403 Forbidden`.
- **Role Governance**: Sensitive role mutations (e.g. assigning `FINANCE` or updating `PayrollPermissionConfig`) are restricted to Rector/Superadmin and logged in `AuditLog`.

## Electronic Signature & Cryptographic Verification Security (Phase 9)

- **Asymmetric Digital Signing**: Ed25519 digital signing over deterministic canonical SHA-256 payload bytes.
- **Key Management Policy**: Private keys are strictly stored in environment configuration (`SIGNATURE_PRIVATE_KEY_B64`) or KMS; never committed to Git, never exposed to templates/JavaScript, and never stored in plain text in PostgreSQL.
- **Deterministic Canonical Serialization**: Reconstructable UTF-8 JSON representation with alphabetical key sorting and standardized ISO-8601 formatting.
- **Tamper Detection**: Snapshot re-serialization and cryptographic verification at verification time detects any record or signature tampering.
- **Public Verification Privacy**: `/verify/<verification_id>/` exposes only non-sensitive official task metadata; strictly excludes employee salary, phone, email, and private notes.
- **Concurrency & Immutability**: Atomic locking (`select_for_update`) prevents double-signing. Signed task records, approvals, and attached evidence become immutable.

## Audit

Audit important operations:

- **Files & Reports**:
  - `FILE_UPLOADED`, `FILE_DOWNLOADED`, `FILE_DELETED`, `FILE_REPLACED`, `FILE_MOVED`
  - `FOLDER_CREATED`, `FOLDER_RENAMED`, `FOLDER_DELETED`
  - `REPORT_CREATED`, `REPORT_UPDATED`, `REPORT_DELETED`, `REPORT_EXPORTED`
  - `SUBMISSION_VERSION_CREATED`
- **HR & Governance**:
  - `USER_CREATED`, `USER_UPDATED`, `USER_ACTIVATED`, `USER_DEACTIVATED`
  - `ROLE_ASSIGNED`, `ROLE_REMOVED`, `FINANCE_ROLE_ASSIGNED`
  - `EMPLOYEE_DEPARTMENT_CHANGED`, `EMPLOYEE_POSITION_CHANGED`, `EMPLOYEE_GRADE_CHANGED`, `EMPLOYEE_SUPERVISOR_CHANGED`, `EMPLOYEE_STATUS_CHANGED`
  - `HR_PERMISSION_CHANGED`
- **Payroll & Compensation**:
  - `SALARY_CREATED`, `SALARY_UPDATED`, `SALARY_DEACTIVATED`, `SALARY_CHANGED`, `SALARY_VIEWED`
  - `PAYROLL_PERIOD_CREATED`, `PAYROLL_PERIOD_OPENED`, `PAYROLL_CALCULATED`, `PAYROLL_SUBMITTED`, `PAYROLL_APPROVED`, `PAYROLL_PAID`, `PAYROLL_CLOSED`
  - `PAYROLL_ADJUSTMENT_CREATED`, `PAYROLL_ADJUSTMENT_APPROVED`
  - `PAYROLL_PERMISSION_CHANGED`, `PAYROLL_EXPORT_CREATED`
- **Electronic Signatures & Cryptographic Verification (Phase 9)**:
  - `SIGNATURE_CREATED`, `SIGNATURE_VERIFIED`, `SIGNATURE_REVOKED`, `SIGNATURE_VERIFICATION_FAILED`, `SIGNATURE_KEY_ROTATED`

Audit logs are visible to the Rector and Superadmin only via `/audit/` (403 for all other roles).

