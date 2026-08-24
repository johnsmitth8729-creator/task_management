# Analytics Architecture

## Goal

The platform must later support monitoring, dashboards, reporting, workload, performance, KPI, and payroll statistics.

## Metrics

Planned analytics include:

- total tasks
- active tasks
- completed tasks
- rejected tasks
- overdue tasks
- pending approvals
- department performance
- employee performance
- completion rate
- on-time rate
- rejection rate
- workload
- KPI
- payroll statistics

## Data Sources

Analytics should read from:

- Task
- TaskAssignment
- TaskSubmission
- TaskApproval
- TaskHistory
- DeadlineChange
- KPI/KPISnapshot
- Payroll
- SalaryAdjustment

## Architecture

Use selector/query services for analytics first. Add materialized views or aggregate tables only when performance requires them.

Recommended layers:

- query selectors for scoped metrics
- aggregate service functions
- cached dashboard summaries
- Celery jobs for heavy recalculation
- report generation services for exportable analytics

## Workload Architecture

Future workload calculations may use:

- active tasks
- task complexity
- priority
- estimated effort
- deadlines
- subtasks
- employee capacity

Expected outputs:

- employee workload percentage
- department workload
- overloaded employees
- available capacity

Do not hardcode a workload formula in early phases. Store configurable weights or rules once workload calculation is implemented.

## Permission Scope

Analytics must follow the same scope rules as operational data:

- Rector sees all.
- Vice Rector sees assigned departments.
- Department Head sees own department.
- Employee sees own data only.

Payroll analytics must use stricter payroll permissions.

## Historical Integrity

Analytics should be reproducible from historical records. For official KPI/payroll reporting, use snapshots.

