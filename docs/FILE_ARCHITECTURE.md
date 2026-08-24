# File Architecture

## Goals

The system must support task-related file uploads while preventing uncontrolled public access.

Allowed file categories:

- PDF
- DOC, DOCX
- XLS, XLSX
- PPT, PPTX
- CSV
- TXT
- ZIP, RAR
- JPG, JPEG, PNG

Allowed extensions must be configurable by administrators.

## Storage Model

Use `TaskAttachment` for file metadata:

- task
- submission optional
- uploaded_by
- original filename
- stored filename
- extension
- MIME type
- size
- storage path
- checksum
- uploaded_at
- deleted_at optional

## Security Requirements

- Do not expose uploaded files through uncontrolled public URLs.
- Store files outside public static directories.
- Serve downloads through Django permission-controlled views.
- Validate extension and MIME type.
- Enforce configurable file size limit.
- Generate safe stored filenames.
- Avoid trusting user-provided filenames.
- Record upload and delete events in audit logs.
- Consider antivirus scanning hook before production.

## Download Authorization

Download checks must validate:

- user can view the task
- user can view the attachment's submission/comment scope
- attachment is not deleted
- attachment belongs to the expected task

## Future Features

Architecture should allow:

- attachment versioning
- per-file visibility scopes
- private manager-only files
- signed temporary URLs if storage backend requires them
- object storage backend such as S3-compatible storage
- virus scanning
- file retention rules

