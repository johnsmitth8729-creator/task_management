# Security Hardening & Universal RBAC Guidelines (Phase 15)

## 1. Multi-Layered Defense Model
The University Task Management Platform enforces security across 5 concentric layers:

```
[Layer 1: Network & Edge]       ─► TLS 1.3, Rate Limiting Middleware, Brute-Force Blockers
[Layer 2: HTTP Security]        ─► CSP, HSTS, X-Frame-Options: DENY, X-Content-Type-Options: nosniff
[Layer 3: Authentication/RBAC]  ─► Role Mixins (Rector, VR, Dept Head, HR, Finance), Custom Middleware
[Layer 4: Universal Privacy]    ─► Strict Salary & Financial Privacy Enforcement
[Layer 5: Data Storage]         ─► Database Transaction Isolation, Checksum-Verified Backups
```

## 2. Universal Salary Privacy Mandate
- **Rule**: Individual salary profiles, base compensation amounts, bonuses, adjustments, and payslips are **restricted exclusively to the Finance role and Superadmin**.
- **Enforcement Points**:
  - `payroll/views.py`: Enforced by `FinanceRequiredMixin`.
  - `ai_assistant/services.py` (`RoleContextBuilder`): Financial query filtering suppresses individual remuneration data for non-Finance users.
  - `core/views.py` (`GlobalSearchView`): Financial tables are excluded from general searches.
  - Reports & Analytics: Only aggregated/anonymized departmental averages are exposed to Executive leadership.

## 3. Active Security Middleware Suite
- `SecurityHeadersMiddleware`: Emits `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, and W3C CSP headers.
- `RateLimitingMiddleware`: Protects `/accounts/login/` (30 reqs/min) and `/health/` (120 reqs/min) using client IP tracking and Redis/cache counters.
- `CustomErrorPageMiddleware`: Serves uniform university-branded 403, 404, 500 error templates without leaking backend tracebacks.

## 4. Electronic Signature Cryptographic Integrity
- Each signed task submission generates a SHA256 payload hash combining user ID, timestamp, task UUID, and digital cert token.
- Modifying a completed task invalidates its signature certificate verification status.
