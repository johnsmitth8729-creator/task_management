# KPI Architecture

## Phase Boundary

Phase 0 designs KPI architecture only. It does not implement KPI calculation.

## Goal

The platform must later calculate configurable KPI scores using task and workflow data. KPI must not use a hardcoded final formula.

## KPI Inputs

Possible KPI factors:

- task quantity
- task complexity
- task priority
- deadline compliance
- quality
- workload
- approved work
- rejected work
- manager evaluation

## Periods

KPI must support:

- monthly
- quarterly
- yearly

## Core Models

### KPIRule

Configurable rule definition:

- code
- name
- period type
- weight
- metric source
- condition JSON
- formula/expression JSON or reference
- active flag
- effective dates

### KPI

Calculated KPI summary:

- employee
- period type
- period start
- period end
- score
- status
- calculated_at

### KPISnapshot

Immutable calculation snapshot:

- KPI record
- input data JSON
- rule results JSON
- final score
- created_at

## Data Sources

KPI engine should read from:

- completed tasks
- approval decisions
- rejection records
- deadline compliance
- priority and complexity
- workload summaries
- manager evaluations when added

## Design Rules

- Use stable metric codes.
- Store rule configuration separately from calculation results.
- Preserve snapshots so future rule changes do not rewrite historical KPI.
- Make recalculation explicit and auditable.
- Keep salary/payroll calculation separate from KPI calculation.

## Integration With Payroll

Payroll may consume approved KPI results or KPI snapshots. Payroll must not recalculate KPI independently.

