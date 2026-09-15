# File, Document & Report Architecture (Phase 6)

## 1. Overview

The Task Management platform features a modular, secure, and production-grade file, document, and report subsystem located in the `files/` Django application. It manages work evidence, logical directory structures, structured work reports, and document export engines (PDF, DOCX, XLSX).

## 2. Models Architecture

### A. `TaskFolder`
Represents logical directory hierarchy per task:
- `id`: UUID (Primary Key)
- `task`: Foreign Key to `tasks.Task` (CASCADE)
- `name`: Folder name (max 150 chars)
- `parent_folder`: Recursive Foreign Key (hierarchical folder trees)
- `created_by`: Foreign Key to `accounts.User`
- `is_active`: Soft-deletion state
- Unique constraint on active folders per parent within task

### B. `TaskFile`
Represents stored files, deliverables, and attachments:
- `id`: UUID (Primary Key)
- `task`: Foreign Key to `tasks.Task` (CASCADE)
- `assignment`: Optional link to `TaskAssignment`
- `submission`: Optional link to `TaskSubmission` (submission version immutability)
- `folder`: Optional link to `TaskFolder`
- `uploaded_by`: Foreign Key to `accounts.User`
- `file`: `FileField` stored under randomized, collision-resistant path
- `original_filename`: Sanitized original name
- `stored_filename`: Physical path key
- `file_extension`: Lowercase extension without dot
- `content_type`: Verified MIME type
- `file_size`: Size in bytes
- `checksum`: SHA-256 hash for integrity & deduplication
- `category`: `WORK_EVIDENCE`, `REQUIREMENTS`, `REPORT_ATTACHMENT`, `APPROVAL_DOCUMENT`, `FINAL_SUBMISSION`, `GENERAL`
- `version`: Positive integer matching submission version
- `is_active`: Soft-deletion flag
- `deleted_at`, `deleted_by`: Audit trail for deletions

### C. `TaskReport`
Structured work reports generated for task milestones:
- `id`: UUID (Primary Key)
- `task`: Foreign Key to `tasks.Task`
- `assignment`: Optional link to `TaskAssignment`
- `author`: Foreign Key to `accounts.User`
- `title`: Report title
- `reporting_period`: Milestone or reporting cycle (e.g. Q3 2026)
- `summary`: Executive overview
- `completed_work`: Detailed activity breakdown
- `results`: Key outcomes, deliverables, metrics
- `problems`: Obstacles and risk log
- `recommendations`: Proposed follow-up actions
- `conclusion`: Final assessment
- `status`: `DRAFT`, `SUBMITTED`, `APPROVED`, `REJECTED`
- `version`: Version counter

## 3. Security & Validation Rules

- **Extension Whitelist**: `pdf`, `doc`, `docx`, `xls`, `xlsx`, `csv`, `ppt`, `pptx`, `txt`, `jpg`, `jpeg`, `png`, `webp`, `gif`, `mp4`, `webm`, `zip`, `rar`.
- **Executable Rejection**: Strictly forbids `exe`, `bat`, `cmd`, `ps1`, `sh`, `dll`, `scr`, `vbs`, `js`, `jar`, `msi`, `com`, `pif`, `hta`, `cpl`, `iso` (including hidden secondary extensions).
- **Size Limits**: Configurable in settings (`MAX_FILE_SIZE_MB=50`, `MAX_VIDEO_SIZE_MB=200`, `MAX_TOTAL_SUBMISSION_SIZE_MB=250`).
- **Filename Sanitization**: Automatically strips path traversal characters (`..`, `/`, `\`), null bytes (`\x00`), and unsafe symbols.
- **Protected File Streaming**: Files are never served directly via public URLs. All downloads (`/files/<uuid>/download/`) and inline previews (`/files/<uuid>/view/`) verify server-side authentication, role authorization, department scoping, and active file status.
- **IDOR Protection**: Direct UUID requests verify whether the requesting user is in the authorized department or assigned to the task.

## 4. Export Engines

- **PDF Engine (`reportlab`)**: Professional university-branded PDF completion reports and work reports with header logos, styled tables, and metadata.
- **Word Engine (`python-docx`)**: Generates fully formatted, editable `.docx` documents.
- **Excel Engine (`openpyxl`)**: Generates styled `.xlsx` spreadsheets with header styling, wrapped cells, and metrics.

## 5. Electronic / QR Signature & Cryptographic Verification Integration (Phase 9)

In Phase 9, electronic signature and QR verification have been fully integrated with the file and reporting architecture:
- **Canonical Payload Checksums**: `signatures.crypto.canonical_json` aggregates task files and submission deliverables along with their SHA-256 `checksum` hashes, guaranteeing immutable evidence binding.
- **ReportLab PDF Signature Block**: `files.exports.export_task_pdf` automatically renders an official University Electronic Signature verification seal, signer identity, timestamp, canonical SHA-256 payload digest, and an embedded 2D QR Code image linking to public verification endpoint `/verify/<verification_id>/`.
- **Public Verification Privacy**: Public verification strictly omits internal file paths, internal storage keys, or raw attachments, protecting university intellectual property and employee privacy.
