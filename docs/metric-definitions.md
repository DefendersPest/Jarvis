# Metric Definitions (to be confirmed by management)

All metrics are computed in `jarvis/metrics/engine.py` from rows ingested from FieldRoutes. A metric is **UNAVAILABLE** (never zero) when a data feed it depends on didn't load for the full window, or when the source doesn't supply the field. The reason is shown in the report.

**Period:**

- Tuesday to Friday reports cover the previous day.
- Monday reports cover Friday through Sunday.
- **MTD** runs from the 1st of the month through the last day covered.

| Key | Definition | Depends on | Decision needed |
|---|---|---|---|
| `revenue_billed_day` / `_mtd` | Sum of invoice (ticket) **subtotal, before tax**, by invoice date | invoices | Is "revenue" billed (invoiced) or collected? Pre-tax? Include initial services? Currently: billed, pre-tax, all services. |
| `revenue_collected_day` / `_mtd` | Sum of **successful** payment amounts by payment date (includes prepayments) | payments | Exclude refunds or credits? |
| `open_balance_mtd` | Unpaid balance remaining on invoices dated this month, as of the latest sync | invoices | - |
| `avg_ticket_day` | Billed revenue ÷ number of invoices in the period | invoices | - |
| `appointments_scheduled_day` | Appointments whose scheduled date is in the period, any status | appointments | - |
| `appointments_completed_day` | Of those, status = completed | appointments | - |
| `appointments_missed_day` | Of those, still **pending** after the date passed (not completed, rescheduled or cancelled) | appointments | Confirm this matches how the office uses statuses |
| `completion_rate_day` | completed ÷ (completed + missed + no-show). Rescheduled and cancelled appointments are excluded. | appointments | Include rescheduled in the denominator? |
| `appointments_no_show_day`, `_rescheduled_day`, `_cancelled_day` | Counts by status | appointments | Status code mapping must be verified (`fieldroutes_mapping.py`) |
| `completed_without_invoice_day` | Completed appointments with no linked invoice, or a $0 invoice | appointments, invoices | Some services are legitimately $0 (warranty re-services), so an exclusion list may be needed |
| `new_customers_day` / `_mtd` | Customers whose `dateAdded` is in the period | customers | - |
| `new_subscriptions_day` / `_mtd` | Subscriptions whose `dateAdded` is in the period ("sales") | subscriptions | Count sales by subscription or by customer? Include one-time services? |
| `sold_annual_value_*` | Sum of FieldRoutes' own annual value field for those subscriptions. **Never estimated**: unavailable if FieldRoutes doesn't report it. | subscriptions | Confirm which FieldRoutes field represents contract value |
| `cancellations_day` / `_mtd` | Subscriptions whose `dateCancelled` is in the period | subscriptions | Subscription-level vs customer-level churn |
| `cancelled_annual_value_*` | Annual value of those cancellations (never estimated) | subscriptions | - |
| `net_subscriptions_mtd` | new_subscriptions_mtd minus cancellations_mtd | subscriptions | - |

**Technician production:**

- Per technician (`servicedBy`, falling back to the assigned employee): scheduled, completed, missed (pending + no-show), completion %, and production.
- **Production** is the invoice subtotal linked to the technician's completed appointments.
- **Average per stop** is production ÷ completed stops.

**Sales performance:** per `soldBy` employee, the subscriptions sold and annual value, for the period and MTD.

**Goals and pacing:**

- Monthly goals are compared against **pace**: target × (company workdays elapsed ÷ workdays in the month). Workdays come from `companies.workdays`; for example, The Defenders runs Mon-Sat.
- Daily goals are scaled by the workdays in the period.
- Rate goals (completion rate) are compared directly.
- **Status:**
  - On track: at least 100% of pace.
  - At risk: 90-100% of pace.
  - Behind: below 90% of pace.
  - Lower-is-better goals (cancellations, missed appointments) are inverted.

**Issue rules** (deterministic; each one becomes an `agent_findings` row):

| Rule | Severity |
|---|---|
| Revenue, collections or sales behind goal pace | High if below 90%, medium if 90-100% |
| Missed appointments | High if more than 5% of scheduled |
| Technician completing under 80% of due stops (5 or more due) | Medium |
| Completed services with no or $0 invoice | Medium |
| Cancellations exceeding new sales in the period | Medium |
| Net subscriptions negative MTD | High |
| Failed payments | Low |
| Data gaps | Info |
