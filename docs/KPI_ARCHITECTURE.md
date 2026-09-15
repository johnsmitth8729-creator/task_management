# KPI ARCHITECTURE & PERFORMANCE GOVERNANCE

## 1. Objective & Scope
The KPI engine provides transparent, mathematical, role-scoped performance measurement for university personnel, departments, and vice-rector sectors.

---

## 2. Model Structure
1. **`KPICategory`**: High-level classification (e.g. Task Execution, Quality Standards, Innovation, Compliance).
2. **`KPIPeriod`**: Evaluation cycle (`MONTHLY`, `QUARTERLY`, `YEARLY`) with statuses: `DRAFT` $\to$ `OPEN` $\to$ `CLOSED`.
3. **`KPIDefinition`**: Indicator template with target value, weight, measurement type (`PERCENTAGE`, `NUMERIC`, `BOOLEAN`, `COUNT`, `RATING`).
4. **`KPIAssignment`**: Indicator bound to an employee for a specific period.
5. **`KPIResult`**: Recorded score with evaluation notes, evaluator reference, and approval status (`DRAFT`, `SUBMITTED`, `REVIEWED`, `APPROVED`).

---

## 3. Mathematical Scoring Engine

$$\text{Raw Score} = \min\left(100, \frac{\text{Actual Value}}{\text{Target Value}} \times 100\right)$$

$$\text{Weighted Score} = \frac{\text{Raw Score} \times \text{Weight}}{100}$$

$$\text{Total Performance Score} = \sum_{i=1}^n \text{Weighted Score}_i$$

- Task completion rate and deadline compliance rate are dynamically calculated by the service layer directly from historical task records.

---

## 4. Role-Scoped KPI Visibility (Anti-IDOR)
- **Employee**: Can only view own performance dashboard and KPI breakdown.
- **Department Head**: Can view own department's performance scorecard, team headcount, and employee metrics.
- **Vice Rector**: Can view supervised sectors and department comparative performance.
- **Rector / HR / Superadmin**: University-wide performance overview, global KPI average, and department rankings.
