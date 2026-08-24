# Payroll Architecture

## Phase Boundary

Phase 0 designs payroll architecture only. It does not implement payroll calculation.

## Goal

The system will later support KPI-based salary/bonus calculation:

Base Salary + KPI Bonus + Additional Bonus - Deduction = Calculated Salary

The system is not a full accounting system. It is a configurable KPI-based salary/bonus calculation engine.

## Core Models

### PayrollRule

Fields:

- code
- name
- rule type
- configuration JSON
- active flag
- effective dates

### Payroll

Fields:

- employee
- period start
- period end
- base salary
- KPI bonus
- additional bonus
- deduction
- calculated salary
- status
- generated_by
- generated_at

### SalaryAdjustment

Fields:

- payroll
- employee
- adjustment type
- amount
- reason
- created_by
- created_at

## Permission Requirements

Salary and payroll information is confidential.

Default access:

- Rector: full access
- Vice Rector: no payroll access unless explicitly delegated
- Department Head: no payroll access by default
- Employee: own payroll summary only if enabled

Every payroll view/export/API must use strict permission checks and audit access where appropriate.

## KPI Integration

Payroll should consume finalized KPI records or snapshots. It should not directly compute task performance.

## Historical Integrity

Payroll outputs should be snapshot-based. Rule changes must not silently change past payroll records.

## Ambiguities To Decide Later

- Whether employees can view calculated salary in the platform.
- Whether Vice Rectors can view payroll for assigned departments.
- Whether Department Heads can view bonus-only summaries without salary.
- Approval process for payroll snapshots.

