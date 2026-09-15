# AI Assistant & Management Intelligence Architecture (Phase 14)

## 1. Overview
The AI Assistant & Management Intelligence module provides executive decision support, risk detection, automated operational briefings, and interactive role-scoped natural language assistance while rigorously enforcing institutional salary privacy and RBAC.

## 2. Core Architecture
```
                  ┌────────────────────────────────────────┐
                  │              User Prompt               │
                  └──────────────────┬─────────────────────┘
                                     │
                                     ▼
                  ┌────────────────────────────────────────┐
                  │          RoleContextBuilder            │
                  │  - Scopes Tasks by User Role/Dept      │
                  │  - Scopes SLA / Risk Metrics           │
                  │  - STRICT SALARY PRIVACY MASKING       │
                  └──────────────────┬─────────────────────┘
                                     │
                                     ▼
                  ┌────────────────────────────────────────┐
                  │           AIAssistantEngine            │
                  │  - Intent Analysis & Query Parsing     │
                  │  - Synthesizes Structured Responses    │
                  │  - Generates Actionable Insights       │
                  └──────────────────┬─────────────────────┘
                                     │
                                     ▼
                  ┌────────────────────────────────────────┐
                  │       Persistent AI Conversation       │
                  │       (AIConversation / AIMessage)     │
                  └────────────────────────────────────────┘
```

## 3. Strict Salary Privacy Guarantee
- The `RoleContextBuilder` explicitly verifies whether `user.role_code == 'FINANCE'` or `user.is_superuser`.
- If the caller does not hold Finance or Superadmin privileges, **individual salary numbers and compensation records are completely omitted and masked** from prompt injection context, preventing any unauthorized financial data leakage.

## 4. Risk Detection Algorithms (`RiskDetectionEngine`)
The engine continuously evaluates institutional operational health across 3 dimensions:
1. **`DEADLINE_OVERFLOW`**: Detects statistical spikes in upcoming deadlines within 48-hour sliding windows.
2. **`BOTTLENECK`**: Identifies approval queues where tasks remain pending longer than 72 hours under specific approvers.
3. **`WORKLOAD_IMBALANCE`**: Detects employee overload (>5 active critical tasks assigned to a single staff member).

## 5. Automated Executive Briefings
- `ExecutiveReportGenerator` dynamically compiles executive status reports for Rectors and Vice Rectors.
- Summarizes completion rates, department SLA performance, critical bottlenecks, and strategic recommendations into `ExecutiveBriefing` records.
