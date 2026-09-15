# ORGANIZATIONAL HIERARCHY & SUPERVISORY GOVERNANCE

## 1. Enterprise Authority Architecture

The Task Management Platform models a clean, role-scoped institutional hierarchy with clear separation between **Technical Administration** and **Operational University Leadership**.

```
                         TECHNICAL SUPERADMIN
                                  │
                                  │ (Django Admin / System Config / Infrastructure)
                                  ▼
                      UNIVERSITY ORGANIZATION
                                  │
                                  ├── RECTOR (Highest Operational Authority)
                                  │       │
                                  │       ├── VICE RECTORS (Sector Authority)
                                  │       │       │
                                  │       │       └── SUPERVISED DEPARTMENTS
                                  │       │
                                  │       └── UNIVERSITY-WIDE GOVERNANCE
                                  │
                                  ├── DEPARTMENTS
                                  │       │
                                  │       └── DEPARTMENT HEAD (Departmental Authority)
                                  │               │
                                  │               └── DIRECT SUPERVISORS / TEAM LEADS
                                  │                       │
                                  │                       └── EMPLOYEES / SUBORDINATES
                                  │
                                  └── HR (Employee Governance & Cataloging)
```

---

## 2. Distinction of Core Concepts

| Concept | Definition | Key Examples | Supervisory Authority? |
| :--- | :--- | :--- | :--- |
| **User** | Authentication and individual user account. | `akbar.rahmatov`, `bekzod.nazarov` | No |
| **Role** | System-level permission capability (`Role.Codes`). | `SUPERADMIN`, `RECTOR`, `VICE_RECTOR`, `DEPARTMENT_HEAD`, `HR`, `EMPLOYEE` | Sets macro access |
| **Department** | Academic or administrative unit. | `Information Technology`, `University Library`, `Finance & Accounting` | Scopes data boundaries |
| **Position** | Institutional title and structural management status. | `Head of Department` (`can_supervise=True`), `Senior Developer` (`can_supervise=False`) | **Yes, via `can_supervise`** |
| **Grade** | Seniority rank / remuneration level. | `G1`, `G2`, `G3`, `G4`, `G5`, `G6` | **No** (High grade ≠ Manager) |
| **Supervisor** | Explicit recursive reporting relationship (`User.supervisor`). | Direct line manager | **Yes** |

---

## 3. Direct Supervisor Eligibility Rules

An employee is **only** eligible to act as a direct supervisor if they satisfy **all** of the following criteria:

1. **Active Employment Status**: Must be `is_active=True` and `employment_status` in `[ACTIVE, ON_LEAVE]`. Terminated or inactive staff are rejected.
2. **Management Authority**: Must hold a `Position` where `can_supervise=True`, OR hold an executive role (`Role.Codes.RECTOR`, `Role.Codes.VICE_RECTOR`, `Role.Codes.DEPARTMENT_HEAD`).
3. **Exclusion of Technical Superadmin**: `is_superuser=True` accounts are isolated from organizational management and can never be selected as supervisors.
4. **No Self-Supervision**: An employee cannot be their own supervisor ($A \not\to A$).
5. **No Cyclic Reporting Chains**: Recursive cycle detection prevents any circular dependencies ($A \to B \to A$ or $A \to B \to C \to A$).
6. **Departmental Scope Compatibility**:
   - A supervisor must belong to the employee's department (e.g. Department Head or Team Lead), OR
   - Be the assigned Vice Rector over that department, OR
   - Be the Rector (University-wide).

---

## 4. Backend Enforcement

The backend is the sole source of truth. Any manipulated POST request attempting to assign an ordinary employee or incompatible supervisor is rejected with HTTP 400 `ValidationError` and logged to `AuditLog`.
