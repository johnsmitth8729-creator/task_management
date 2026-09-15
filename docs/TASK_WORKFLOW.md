# University Task Management Platform — Task Workflow Specification

> **Source of Truth Document**  
> This specification reflects the audited, verified, and hardened implementation of the University Task Management Platform.  
> Status codes are stored as stable English enum identifiers in the database and translated dynamically for user interface display.

---

## 1. System Architecture & Model Separation

The platform utilizes a **decoupled, multi-entity workflow architecture** rather than a monolithic task status field. This enables multi-employee task assignments, independent assignee lifecycles, immutable submission versioning, and rigorous audit trails.

```
┌─────────────────────────────────────────────────────────────┐
│                         Task                                │
│ Status: DRAFT, CREATED, ASSIGNED, IN_PROGRESS,              │
│         COMPLETED, CANCELLED, ARCHIVED                      │
│ (Overdue is calculated via `is_overdue`, not a destructive  │
│  database status overwrite)                                 │
└──────────────────────────────┬──────────────────────────────┘
                               │ 1 : N
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    TaskAssignment                           │
│ Status: ASSIGNED, IN_PROGRESS, SUBMITTED,                   │
│         SECOND_APPROVAL, APPROVED, REJECTED                 │
└──────────────────────────────┬──────────────────────────────┘
                               │ 1 : N
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    TaskSubmission                           │
│ Versions: v1, v2, v3 ... (Strictly immutable)               │
│ Status: PENDING_FIRST_APPROVAL, FIRST_APPROVED,             │
│         FIRST_REJECTED, FINAL_APPROVED, FINAL_REJECTED      │
└──────────────────────────────┬──────────────────────────────┘
                               │ 1 : N
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     TaskApproval                            │
│ Stage: FIRST_APPROVAL, SECOND_APPROVAL, FINAL_APPROVAL      │
│ Decision: APPROVED, REJECTED, CHANGES_REQUESTED             │
└─────────────────────────────────────────────────────────────┘
```

### 1.1 Model Roles & Responsibilities
1. **`Task`**: The university directive or project header. Tracks creator, responsible department, secondary departments, overall deadline, overall progress (synced from assignments), and executive lifecycle status.
2. **`TaskAssignment`**: The individual work directive binding a specific employee to the task. Tracks acceptance time, personal progress (0–100%), primary/secondary assignee designation, and current assignment lifecycle stage.
3. **`TaskSubmission`**: The versioned deliverable record (`v1`, `v2`, `v3`...) submitted by the employee. Every submission record is immutable once created.
4. **`TaskApproval`**: The formal audit record of approval or rejection at Level 1 (Department Head) or Level 2 (Rector / Vice Rector). Captures stage, decision, actor, actor role, notes/reason, and timestamp.
5. **`ElectronicSignature`**: The cryptographic Ed25519 signature record generated upon completed and final-approved university tasks by the Rector or Acting Rector.

---

## 2. Status Enums & Lifecycle States

### 2.1 Task Status (`Task.Status`)
| Status Code | Description | Next Permitted States |
|---|---|---|
| `DRAFT` | Initial draft created by executive or department head | `CREATED` |
| `CREATED` | Formally registered in the university system | `ASSIGNED`, `IN_PROGRESS`, `CANCELLED` |
| `ASSIGNED` | Target department and/or employees assigned | `IN_PROGRESS`, `CANCELLED` |
| `IN_PROGRESS` | At least one assignee has accepted or begun work | `COMPLETED`, `CANCELLED` |
| `COMPLETED` | Final executive approval granted; all deliverables approved | `ARCHIVED` |
| `CANCELLED` | Task terminated prior to completion with mandatory reason | `ARCHIVED` |
| `ARCHIVED` | Preserved in the historical university records | *(Terminal)* |

> [!NOTE]
> `OVERDUE` is NOT a database status. In accordance with robust state machine design, overdue state is dynamically derived via the `task.is_overdue` model property (`status not in (COMPLETED, CANCELLED, ARCHIVED) and deadline < today`). This prevents overdue detection from destructively overwriting whether a task is `IN_PROGRESS` or `ASSIGNED`.

### 2.2 Assignment Status (`TaskAssignment.AssignmentStatus`)
| Status Code | Description | Next Permitted States |
|---|---|---|
| `ASSIGNED` | Assigned to employee; awaiting acceptance | `IN_PROGRESS` |
| `IN_PROGRESS` | Accepted by employee; work and progress updates underway | `SUBMITTED` |
| `SUBMITTED` | Deliverable submitted; awaiting Level 1 (Department Head) approval | `SECOND_APPROVAL`, `REJECTED` |
| `SECOND_APPROVAL` | Approved at Level 1; awaiting Level 2 (Rector / Vice Rector) approval | `APPROVED`, `REJECTED` |
| `APPROVED` | Final executive approval granted | *(Terminal)* |
| `REJECTED` | Submission rejected at Level 1 or Level 2; rework required | `IN_PROGRESS`, `SUBMITTED` |

### 2.3 Submission Status (`TaskSubmission.SubmissionStatus`)
| Status Code | Description |
|---|---|
| `PENDING_FIRST_APPROVAL` | Newly submitted version awaiting Department Head review |
| `FIRST_APPROVED` | Approved by Department Head; forwarded to executive review |
| `FIRST_REJECTED` | Rejected by Department Head; rework required |
| `FINAL_APPROVED` | Approved by Rector or responsible Vice Rector |
| `FINAL_REJECTED` | Rejected by Rector or responsible Vice Rector; rework required |

---

## 3. End-to-End Workflow Transitions

| Transition | Actor | Permission & Scope Check | Database Mutations | Notifications | Audit & History Events |
|---|---|---|---|---|---|
| **Create Task** | Rector, Vice Rector, Superadmin | `can_create_task`: Rector university-wide; Vice Rector within assigned departments | Create `Task(status=CREATED)` | Optional draft alert | `TASK_CREATED` |
| **Assign Department / Employees** | Rector, scoped Vice Rector, Department Head | `can_assign_employees_to_task`: Dept Head only within own department; Vice Rector within responsible departments; Rector university-wide | Create `TaskAssignment(status=ASSIGNED)`, set `Task(status=ASSIGNED)` | Notify assigned employees (`TASK_ASSIGNED`) | `TASK_EMPLOYEE_ASSIGNED` |
| **Accept Task** | Assigned Employee | `can_accept_assignment`: user is assignee, assignment is `ASSIGNED`, task active | Set `assignment_status=IN_PROGRESS`, `accepted_at=now()`; set `task.status=IN_PROGRESS` | Notify Department Head | `TASK_ACCEPTED` |
| **Update Progress** | Assigned Employee | `can_update_assignment_progress`: user is assignee, assignment `IN_PROGRESS` | Update `assignment.progress` (0–100%); recalculate `task.progress` | Optional threshold notification | `TASK_PROGRESS_UPDATED` |
| **Submit Deliverable (V1)** | Assigned Employee | `can_submit_assignment`: user is assignee, assignment `IN_PROGRESS`, task active | Create `TaskSubmission(v1, PENDING_FIRST_APPROVAL)`; set `assignment_status=SUBMITTED`, `progress=100` | Notify Department Head (`TASK_SUBMITTED`) | `TASK_SUBMISSION_CREATED` |
| **First Approval (Level 1)** | Department Head | `can_first_approve_assignment`: Dept Head of responsible department or assignee's department | Set `assignment_status=SECOND_APPROVAL`, `submission.status=FIRST_APPROVED`; create `TaskApproval(FIRST_APPROVAL, APPROVED)` | Notify Rector / responsible Vice Rector (`FIRST_APPROVAL_APPROVED`) | `FIRST_APPROVAL_GRANTED` |
| **First Rejection (Level 1)** | Department Head | `can_first_reject_assignment`: Dept Head of responsible department; mandatory reason required | Set `assignment_status=REJECTED`, `submission.status=FIRST_REJECTED`; create `TaskApproval(FIRST_APPROVAL, REJECTED)` | Notify Employee (`FIRST_APPROVAL_REJECTED`) | `FIRST_APPROVAL_REJECTED` |
| **Start / Resume Rework** | Assigned Employee | `can_start_rework`: user is assignee, assignment `REJECTED`, task active | Set `assignment_status=IN_PROGRESS`; revert `task.status=IN_PROGRESS` if completed | Notify Department Head (`GENERAL`) | `TASK_REWORK_STARTED` |
| **Submit Revised Deliverable (V2+)** | Assigned Employee | `can_submit_assignment`: user is assignee, assignment `IN_PROGRESS` or `REJECTED` | Create `TaskSubmission(v2, PENDING_FIRST_APPROVAL)`; set `assignment_status=SUBMITTED`, `progress=100` | Notify Department Head (`TASK_SUBMITTED`) | `TASK_SUBMISSION_CREATED` |
| **Final Approval (Level 2)** | Rector, scoped Vice Rector, Acting Rector | `can_final_approve_assignment`: Rector university-wide; Vice Rector within responsible departments | Set `assignment_status=APPROVED`, `task.status=COMPLETED`, `completed_at=now()`, `submission.status=FINAL_APPROVED`; create `TaskApproval(FINAL_APPROVAL, APPROVED)` | Notify Employee and Department Head (`FINAL_APPROVED`) | `FINAL_APPROVAL` |
| **Final Rejection (Level 2)** | Rector, scoped Vice Rector, Acting Rector | `can_second_reject_assignment`: Rector university-wide; Vice Rector within responsible departments; mandatory reason required | Set `assignment_status=REJECTED`, `submission.status=FINAL_REJECTED`, revert `task.status=IN_PROGRESS`; create `TaskApproval(SECOND_APPROVAL, REJECTED)` | Notify Employee and Department Head (`FINAL_REJECTED`) | `SECOND_APPROVAL_REJECTED` |
| **Extend Deadline** | Rector, scoped Vice Rector | `can_extend_task_deadline`: Rector university-wide; Vice Rector within responsible departments; mandatory reason required | Update `task.deadline`; create `TaskDeadlineExtension` | Notify Assignees & Department Head (`DEADLINE_EXTENDED`) | `DEADLINE_EXTENDED` |
| **Cancel Task** | Rector, scoped Vice Rector, Creator | `can_cancel_task`: task active; mandatory reason required | Set `task.status=CANCELLED`, `task.cancelled_at=now()` | Notify all participants | `TASK_CANCELLED` |
| **Archive Task** | Rector, scoped Vice Rector | `can_archive_task`: task is `COMPLETED` or `CANCELLED` | Set `task.status=ARCHIVED`, `task.archived_at=now()` | Internal audit log | `TASK_ARCHIVED` |

---

## 4. The Rework Loop Specification

When an assignment is rejected by the Department Head (Level 1) or by the Rector / Vice Rector (Level 2):
1. **Assignment Status**: Set to `REJECTED`.
2. **Submission Status**: Marked `FIRST_REJECTED` or `FINAL_REJECTED`.
3. **Rejection Reason**: Persisted in `TaskApproval` and displayed prominently to the employee.
4. **Resuming Work**:
   - The employee clicks **Start / Resume Rework** (or submits directly).
   - Calling `start_rework()` sets `assignment_status = IN_PROGRESS` and creates `TaskHistory(TASK_REWORK_STARTED)`.
   - If the task was previously marked `COMPLETED`, it automatically reverts to `IN_PROGRESS` and clears `completed_at`.
5. **New Version Creation**:
   - When the employee resubmits, the system queries the highest version number (`v1`) and increments it (`v2`, `v3`...).
   - A new `TaskSubmission` is created with status `PENDING_FIRST_APPROVAL`.
   - `assignment_status` moves to `SUBMITTED`.
   - Previous versions (`v1`) remain **completely immutable**, preserving the historical deliverable text, files, and rejection comments.
   - The revised submission returns to Level 1 approval by the Department Head.

---

## 5. Role Authorities Matrix

| Action / Capability | Superadmin | Rector | Acting Rector | Vice Rector | Department Head | Employee |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Create Task** | Yes | Yes (Univ-wide) | Yes (Univ-wide) | Yes (Scoped) | Yes (Draft/Own) | No |
| **Assign Employees** | Yes | Yes (Univ-wide) | Yes (Univ-wide) | Yes (Scoped) | Yes (Own Dept) | No |
| **Accept Task** | Bypass | No | No | No | Only if assigned | Yes (Own) |
| **Update Progress** | Bypass | No | No | No | Only if assigned | Yes (Own) |
| **Submit Deliverables** | Bypass | No | No | No | Only if assigned | Yes (Own) |
| **Level 1 (First) Approve / Reject** | Yes | No | No | No | **Yes (Responsible Dept)** | No |
| **Level 2 (Final) Approve / Reject** | Yes | **Yes (Univ-wide)** | **Yes (Univ-wide)** | **Yes (Scoped)** | **No** | No |
| **Extend Deadline** | Yes | Yes (Univ-wide) | Yes (Univ-wide) | Yes (Scoped) | No | No |
| **Cancel Active Task** | Yes | Yes (Univ-wide) | Yes (Univ-wide) | Yes (Scoped) | No | No |
| **Archive Task** | Yes | Yes (Univ-wide) | Yes (Univ-wide) | Yes (Scoped) | No | No |
| **Electronic Signing (Ed25519)** | Yes | **Yes** | **Yes** | **No** *(Unless Acting)* | **No** | No |

---

## 6. Phase 9 — Electronic Signature & Cryptographic Verification

Following Level 2 (Final) approval and task completion, the university executive electronically signs the task:

1. **Eligibility**:
   - Task status must be `COMPLETED`.
   - A valid final approval record (`TaskApproval(FINAL_APPROVAL, APPROVED)`) must exist.
   - Task must not already possess an active electronic signature.
2. **Authorized Signers**:
   - **Rector** (`is_rector=True`)
   - **Acting Rector** (`can_act_as_rector=True` via active `ActingRectorDelegation`)
   - **Superadmin** (technical emergency bypass)
   - *Vice Rectors are strictly blocked from signing tasks unless officially designated as Acting Rector.*
3. **Cryptographic Primitives**:
   - **Asymmetric Key Pair**: Ed25519 (256-bit Edwards-curve Digital Signature Algorithm).
   - **Canonical Payload**: Deterministic JSON containing task number, title, creator, responsible department, completion time, final approver, and signer metadata.
   - **Snapshot Generation**: Immutable `SignatureSnapshot` capturing all assignees, deliverables, and approval decisions at the exact moment of signing.
   - **Hash**: SHA-256 digest of the canonical snapshot.
4. **Public Verification & QR Code**:
   - Every signature is assigned a cryptographically random, non-sequential verification identifier (`verification_id`).
   - Dynamically generated SVG QR code pointing to `/verify/<verification_id>/`.
   - The public verification view validates key authenticity, payload integrity, and revocation status without exposing sensitive user credentials.
   - Revocation requires Superadmin or Rector authority with mandatory revocation reason.

---

## 7. Audit Logging & Historical Tracking

Every state transition and administrative action records dual events:
- **`TaskHistory`**: User-facing chronological event stream on the task and assignment detail pages.
- **`AuditLog`**: System-level administrative audit log capturing IP address, actor, action enum, target repr, and structured JSON details.

Key audited events include:
- `TASK_CREATED`, `TASK_ASSIGNED`, `TASK_ACCEPTED`, `TASK_PROGRESS_UPDATED`
- `TASK_SUBMISSION_CREATED`, `TASK_REWORK_STARTED`
- `FIRST_APPROVAL_GRANTED`, `FIRST_APPROVAL_REJECTED`
- `FINAL_APPROVAL`, `SECOND_APPROVAL_REJECTED`
- `DEADLINE_EXTENDED`, `TASK_CANCELLED`, `TASK_ARCHIVED`
- `SIGNATURE_CREATED`, `SIGNATURE_REVOKED`, `SIGNATURE_VERIFIED`
