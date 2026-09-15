# Electronic Signature & Cryptographic Verification Architecture (Phase 9)

## 1. Overview & Objective

The University Task Management Platform provides an enterprise-grade, verifiable electronic signature subsystem. Once a university task achieves final approval, the **Rector** (university-wide authority) or authorized **Vice Rector** (within supervised department responsibility) can electronically sign the completed task.

Each electronic signature record establishes:
- **Unique Verification Identifier** (`SIG-YYYY-XXXXXXXX`) and secure opaque verification URL token.
- **Asymmetric Cryptographic Signature** (Ed25519) binding the signer's authenticated identity to the canonical task deliverable.
- **Cryptographic Hash Integrity** (SHA-256) of a deterministic canonical JSON representation.
- **Immutable Historical Snapshot** (`SignatureSnapshot`) capturing the complete state of the task, assignees, approvers, and attached evidence file checksums at the exact moment of signing.
- **Server-Side QR Code Generation** encoding the public verification URL.
- **Public Verification Service** (`/verify/<verification_id>/`) requiring no login, providing independent verification of document integrity and signer attribution without leaking sensitive personal or financial employee data.
- **Controlled Revocation Lifecycle** with mandatory audit trails.

---

## 2. Terminology & Legal Distinction

- **Electronic Signature (Business Feature)**: The operational and workflow feature within the platform through which university executives review and commit their official digital approval to completed deliverables.
- **Cryptographic Signature**: The asymmetric digital signature (Ed25519) computed over the SHA-256 hash of the canonical serialized business record.
- **Production Security Note**:
  > [!IMPORTANT]
  > The Phase 9 implementation provides robust internal cryptographic signing, immutable snapshot retention, signer attribution, and public QR verification. It does **not** claim legal equivalence to a state-certified Qualified Electronic Signature (QES / E-Imzo) under national PKI legislation unless integrated with an authorized national trust service provider or hardware security module (HSM). The architecture is designed with clean abstraction layers to support such integration.

---

## 3. Cryptographic Architecture

### 3.1 Algorithm Selection
- **Asymmetric Signature**: **Ed25519** (Edwards-curve Digital Signature Algorithm over Curve25519).
  - Fast constant-time operation resistant to side-channel timing attacks.
  - Compact 32-byte public keys and 64-byte signatures.
  - Implemented via Python's standard `cryptography` library (`cryptography.hazmat.primitives.asymmetric.ed25519`).
- **Integrity Hashing**: **SHA-256** (NIST FIPS 180-4).

### 3.2 Key Management & Provider Abstraction
Private keys are never stored as plain text in the PostgreSQL database and are never committed to version control.

Key management is encapsulated by `SignatureKeyProvider`:
- `get_active_private_key()`: Retrieves active Ed25519 private key from environment configuration (`SIGNATURE_PRIVATE_KEY_B64`) or auto-generated cached keypair.
- `get_active_public_key()`: Returns active Ed25519 public key.
- `get_key_version()`: Returns active version string (default: `"v1"`).
- `get_public_key_for_version(version, stored_pem)`: Resolves public key for historical verification, allowing seamless key rotation without invalidating old signatures.
- `export_public_key_pem(key)` / `load_public_key_from_pem(pem)`: SubjectPublicKeyInfo PEM encoding.

---

## 4. Canonical Payload & Deterministic Serialization

To guarantee reproducible cryptographic hashing across migrations or dictionary modifications, data is serialized into a deterministic canonical UTF-8 JSON payload:

Rules enforced by `canonical_json()`:
1. **Sorted Keys**: Lexicographical key sorting.
2. **Minimal Separators**: Compact representation `(',', ':')` with no whitespace padding.
3. **Encoding**: UTF-8 encoding.
4. **Stable Timestamps**: ISO-8601 UTC format (`YYYY-MM-DDTHH:MM:SSZ` or ISO string).
5. **Stable Null Handling**: Explicit `null` values preserved consistently.

### Schema (v1):
```json
{
  "schema_version": 1,
  "signature_version": 1,
  "task_id": "<uuid>",
  "task_number": "TM-000123",
  "title": "...",
  "description": "...",
  "responsible_department_id": "<uuid>",
  "responsible_department_name": "...",
  "priority": "HIGH",
  "complexity": "COMPLEX",
  "deadline": "2026-09-15",
  "completed_at": "2026-09-04T09:15:00Z",
  "assignees": [
    {
      "user_id": "<uuid>",
      "username": "employee.one",
      "display_name": "Aziz Rahimov",
      "is_primary": true
    }
  ],
  "final_approval": {
    "approval_id": "<uuid>",
    "approver_id": "<uuid>",
    "approver_name": "Rector Official",
    "approver_role": "RECTOR",
    "approved_at": "2026-09-04T09:10:00Z",
    "decision": "APPROVED",
    "notes": "..."
  },
  "evidence_files": [
    {
      "file_id": "<uuid>",
      "filename": "security_audit_report.pdf",
      "sha256": "3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b",
      "category": "WORK_EVIDENCE",
      "version": 1
    }
  ],
  "approved_reports": [],
  "signer": {
    "signer_id": "<uuid>",
    "signer_username": "rector",
    "signer_name": "Rector Official",
    "signer_position": "University Rector",
    "signer_department": "",
    "signature_type": "RECTOR_SIGNATURE"
  }
}
```

---

## 5. Signature Lifecycle & State Machine

```
Task Lifecycle:
  CREATED -> ASSIGNED -> IN_PROGRESS -> SUBMITTED -> FIRST_APPROVAL -> FINAL_APPROVED (COMPLETED)
                                                                           |
                                                                           v
                                                               [Sign Electronically]
                                                                           |
                                                                           v
                                                             ElectronicSignature: SIGNED
                                                                           |
                                                       (Optional Governance Revocation)
                                                                           v
                                                             ElectronicSignature: REVOKED
```

- **Prerequisites for Signing**:
  1. Task `status` must be `COMPLETED`.
  2. Final approval record (`TaskApproval` with `stage=FINAL_APPROVAL, decision=APPROVED`) must exist.
  3. No existing active signature (`status=SIGNED`).
  4. Signer must be authorized (Rector university-wide, Vice Rector within departmental scope, or Superadmin).

- **Double-Signing Prevention**:
  `sign_task()` executes within an atomic database transaction (`transaction.atomic()`) with row-level locking (`select_for_update()`) on `Task`. Attempting concurrent or repeated signing raises `ValidationError(_("This task has already been electronically signed."))`.

---

## 6. RBAC & Scoping Rules

| Role | University-wide Signing | Scoped Department Signing | Revocation Authority | View Public Verification |
|---|:---:|:---:|:---:|:---:|
| **Technical Superadmin** | Yes (Administrative) | Yes | Yes | Yes |
| **Rector** | **Yes (Operational)** | **Yes** | **Yes** | Yes |
| **Vice Rector** | ❌ No | **Yes (Scoped Depts Only)** | ❌ No | Yes |
| **Department Head** | ❌ No | ❌ No | ❌ No | Yes |
| **Employee** | ❌ No | ❌ No | ❌ No | Yes |
| **HR Manager** | ❌ No | ❌ No | ❌ No | Yes |
| **Finance Officer** | ❌ No | ❌ No | ❌ No | Yes |
| **Public / Anonymous** | ❌ No | ❌ No | ❌ No | **Yes (Safe Data Only)** |

---

## 7. Public Verification & Data Privacy

### Public Endpoint: `/verify/<verification_id>/`
- **Authentication**: None required (publicly accessible).
- **HTTP Method**: `GET` only (`@require_GET`).
- **Data Privacy**: Strictly enforces privacy boundary.
  - **Exposed**: Verification status, Verification ID, Task Number, Task Title, Department Name, Signer Name, Signer Position, Signing Timestamp, Final Approval Date, Cryptographic Algorithm, Key Version, Integrity Status, Payload SHA-256 Hash.
  - **Strictly Concealed**: Employee salary, personal phone number, email address, private notes, internal task files, internal server tracebacks.

### Tamper Detection Engine
When verification is requested:
1. Canonical payload is loaded from immutable `SignatureSnapshot`.
2. Deterministic bytes are re-serialized and SHA-256 hash is re-computed.
3. Computed hash is compared against stored `payload_hash` and `snapshot_hash`.
4. Cryptographic Ed25519 signature is verified against the public key matching `key_version`.
5. Any mismatch triggers `status='INVALID'` with detailed reason logged in `SignatureVerificationEvent`.

---

## 8. QR Code Architecture

Server-side QR codes are dynamically generated using Python `qrcode` with PIL backend:
- Encodes: Canonical public verification URL (e.g. `https://domain/verify/SIG-2026-XXXXXXXX`).
- Dynamic PNG endpoint: `/signatures/<verification_id>/qr/` (supports `?download=1`).
- Dynamic Base64 Data URI: Used for inline rendering on web pages and ReportLab PDF documents without file system temporary leaks.
- Accessibility: Accompanied by descriptive alt-text and selectable verification ID text.

---

## 9. PDF Report Integration

In `files/exports.py` (`export_task_pdf`), completed and signed tasks include an official electronic signature verification section:
- Status banner (`VALID / AUTHENTIC` or `REVOKED`).
- Signer name and official position.
- Signing timestamp.
- Verification ID & URL path.
- Embedded high-resolution QR code thumbnail.
- Canonical Record Hash (SHA-256).
- Clear semantic distinction: "Electronic Signature of Official Task Record" vs document container checksums, preventing circular hash dependencies.

---

## 10. Threat Model & Security Mitigations

1. **IDOR & Unauthorized Signing**:
   - Backend service layer validates caller permissions against object-level ownership and departmental responsibility (`user.get_scoped_departments()`).
2. **Signature Forgery**:
   - Ed25519 digital signatures cannot be forged without the private key.
3. **Payload Tampering**:
   - Any modification to database records or snapshot JSON changes the recomputed SHA-256 hash, causing immediate `INVALID` status.
4. **Replay & Double Signing**:
   - Enforced by `select_for_update()` and unique constraints on `ElectronicSignature(task)`.
5. **Private Key Exposure**:
   - Private keys are stored in environment configuration or KMS, never in PostgreSQL database tables or client-side assets.
6. **Information Leakage**:
   - Public endpoint uses a separate safe projection dictionary; internal fields and financial models are never passed to the verification template.
