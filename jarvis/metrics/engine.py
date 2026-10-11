"""Deterministic metric engine.

All numbers in the CEO report are computed here, in plain Python over rows in
the central database. The AI layer never computes or invents a number; it only
explains numbers produced by this module (see :mod:`jarvis.ai.grounding`).

Definitions are documented in docs/metric-definitions.md and must be
confirmed by management. Changing a definition happens here and nowhere else.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from jarvis.db import repository as repo
from jarvis.db.models import (
    Appointment,
    Branch,
    Company,
    Customer,
    Employee,
    Goal,
    Invoice,
    Payment,
    Subscription,
)
from jarvis.metrics.types import CompanyMetrics, Finding, GoalComparison, Metric
from jarvis.timeutil import ReportWindow, month_bounds, workdays_between

# Thresholds for the deterministic issue rules. Tune with management.
MISSED_RATE_HIGH = 0.05          # >5% of scheduled appointments missed -> high severity
TECH_MIN_SCHEDULED = 5           # ignore technicians with tiny schedules
TECH_COMPLETION_FLOOR = 0.80     # flag technicians completing <80%
PACE_BEHIND = 0.90               # <90% of goal pace -> behind


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    unit: str
    period: str              # day | mtd
    requires: tuple[str, ...]
    goal_key: str | None = None
    goal_scaling: str = "sum"   # sum (scale target by workdays) | rate (compare directly)


DEFS: list[MetricDef] = [
    MetricDef("revenue_billed_day", "Billed revenue", "usd", "day", ("invoices",), "revenue_billed"),
    MetricDef("revenue_billed_mtd", "Billed revenue MTD", "usd", "mtd", ("invoices",), "revenue_billed"),
    MetricDef("revenue_collected_day", "Collections", "usd", "day", ("payments",), "revenue_collected"),
    MetricDef("revenue_collected_mtd", "Collections MTD", "usd", "mtd", ("payments",), "revenue_collected"),
    MetricDef("open_balance_mtd", "Unpaid balance on MTD invoices", "usd", "mtd", ("invoices",)),
    MetricDef("avg_ticket_day", "Average invoice", "usd_avg", "day", ("invoices",)),
    MetricDef("appointments_scheduled_day", "Appointments scheduled", "count", "day", ("appointments",)),
    MetricDef("appointments_completed_day", "Appointments completed", "count", "day", ("appointments",), "appointments_completed"),
    MetricDef("completion_rate_day", "Completion rate", "pct", "day", ("appointments",), "completion_rate", "rate"),
    MetricDef("appointments_missed_day", "Missed (still pending)", "count", "day", ("appointments",), "appointments_missed"),
    MetricDef("appointments_no_show_day", "No-shows", "count", "day", ("appointments",)),
    MetricDef("appointments_cancelled_day", "Cancelled appointments", "count", "day", ("appointments",)),
    MetricDef("appointments_rescheduled_day", "Rescheduled", "count", "day", ("appointments",)),
    MetricDef("completed_without_invoice_day", "Completed with no/$0 invoice", "count", "day", ("appointments", "invoices")),
    MetricDef("new_customers_day", "New customers", "count", "day", ("customers",), "new_customers"),
    MetricDef("new_customers_mtd", "New customers MTD", "count", "mtd", ("customers",), "new_customers"),
    MetricDef("new_subscriptions_day", "New subscriptions sold", "count", "day", ("subscriptions",), "new_subscriptions"),
    MetricDef("new_subscriptions_mtd", "New subscriptions sold MTD", "count", "mtd", ("subscriptions",), "new_subscriptions"),
    MetricDef("sold_annual_value_day", "Annual value sold", "usd", "day", ("subscriptions",), "sold_annual_value"),
    MetricDef("sold_annual_value_mtd", "Annual value sold MTD", "usd", "mtd", ("subscriptions",), "sold_annual_value"),
    MetricDef("cancellations_day", "Subscription cancellations", "count", "day", ("subscriptions",), "cancellations"),
    MetricDef("cancellations_mtd", "Subscription cancellations MTD", "count", "mtd", ("subscriptions",), "cancellations"),
    MetricDef("cancelled_annual_value_day", "Annual value cancelled", "usd", "day", ("subscriptions",)),
    MetricDef("cancelled_annual_value_mtd", "Annual value cancelled MTD", "usd", "mtd", ("subscriptions",)),
    MetricDef("net_subscriptions_mtd", "Net subscription growth MTD", "count", "mtd", ("subscriptions",)),
]
DEF_BY_KEY = {d.key: d for d in DEFS}

# Goals for these keys are "lower is better".
LOWER_BETTER = {"cancellations", "appointments_missed"}


def _in(d: date | None, start: date, end: date) -> bool:
    return d is not None and start <= d <= end


def _r(x: float) -> float:
    return round(float(x), 2)


class MetricEngine:
    def __init__(self, session: Session):
        self.s = session

    # ------------------------------------------------------------------ public
    def compute_company(self, company: Company, w: ReportWindow) -> CompanyMetrics:
        fetch_start = min(w.day_start, w.mtd_start)
        entities = ("employees", "customers", "subscriptions", "appointments", "invoices", "payments")
        cov = repo.coverage(self.s, company.id, entities, fetch_start, w.day_end)
        ok = {e for e, v in cov.items() if v == "ok"}

        branches = {b.id: b for b in self.s.scalars(select(Branch).where(Branch.company_id == company.id))}
        employees = {
            e.source_id: e for e in self.s.scalars(select(Employee).where(Employee.company_id == company.id))
        }

        def rows(model, date_col, start=fetch_start, end=w.day_end):
            col = getattr(model, date_col)
            return list(
                self.s.scalars(
                    select(model).where(model.company_id == company.id, col >= start, col <= end)
                )
            )

        invoices = rows(Invoice, "invoice_date") if "invoices" in ok else []
        payments = rows(Payment, "payment_date") if "payments" in ok else []
        appts = rows(Appointment, "scheduled_date") if "appointments" in ok else []
        customers = rows(Customer, "date_added") if "customers" in ok else []
        subs_added = rows(Subscription, "date_added") if "subscriptions" in ok else []
        subs_cancel = rows(Subscription, "date_cancelled") if "subscriptions" in ok else []

        D0, D1, M0, M1 = w.day_start, w.day_end, w.mtd_start, w.mtd_end
        values: dict[str, tuple[float, dict]] = {}

        # Revenue
        inv_day = [i for i in invoices if _in(i.invoice_date, D0, D1)]
        inv_mtd = [i for i in invoices if _in(i.invoice_date, M0, M1)]
        values["revenue_billed_day"] = (_r(sum(i.subtotal for i in inv_day)), {"invoices": len(inv_day)})
        values["revenue_billed_mtd"] = (_r(sum(i.subtotal for i in inv_mtd)), {"invoices": len(inv_mtd)})
        values["open_balance_mtd"] = (_r(sum(i.balance or 0 for i in inv_mtd)), {})
        if inv_day:
            values["avg_ticket_day"] = (_r(sum(i.subtotal for i in inv_day) / len(inv_day)), {"invoices": len(inv_day)})
        good_pay = [p for p in payments if p.status == "successful"]
        failed_pay_day = [p for p in payments if p.status == "failed" and _in(p.payment_date, D0, D1)]
        values["revenue_collected_day"] = (
            _r(sum(p.amount for p in good_pay if _in(p.payment_date, D0, D1))),
            {"failed_payments": len(failed_pay_day)},
        )
        values["revenue_collected_mtd"] = (_r(sum(p.amount for p in good_pay if _in(p.payment_date, M0, M1))), {})

        # Operations
        a_day = [a for a in appts if _in(a.scheduled_date, D0, D1)]
        by_status = defaultdict(int)
        for a in a_day:
            by_status[a.status] += 1
        scheduled = len(a_day)
        completed = by_status["completed"]
        # A scheduled appointment that is still "pending" after its date passed was missed.
        missed = by_status["pending"]
        # Completion rate excludes appointments that were legitimately moved/cancelled.
        denom = completed + missed + by_status["no_show"]
        values["appointments_scheduled_day"] = (scheduled, {})
        values["appointments_completed_day"] = (completed, {})
        values["appointments_missed_day"] = (missed, {})
        values["appointments_no_show_day"] = (by_status["no_show"], {})
        values["appointments_cancelled_day"] = (by_status["cancelled"], {})
        values["appointments_rescheduled_day"] = (by_status["rescheduled"], {})
        if denom:
            values["completion_rate_day"] = (_r(completed / denom * 100), {"denominator": denom})

        inv_by_appt: dict[str, float] = defaultdict(float)
        for i in invoices:
            if i.appointment_source_id:
                inv_by_appt[i.appointment_source_id] += i.subtotal
        done = [a for a in a_day if a.status == "completed"]
        no_inv = [a for a in done if inv_by_appt.get(a.source_id, 0) <= 0]
        values["completed_without_invoice_day"] = (len(no_inv), {})

        # Customers, sales, cancellations
        values["new_customers_day"] = (len([c for c in customers if _in(c.date_added, D0, D1)]), {})
        values["new_customers_mtd"] = (len([c for c in customers if _in(c.date_added, M0, M1)]), {})
        for suffix, (s0, s1) in {"day": (D0, D1), "mtd": (M0, M1)}.items():
            sold = [x for x in subs_added if _in(x.date_added, s0, s1)]
            cancelled = [x for x in subs_cancel if _in(x.date_cancelled, s0, s1)]
            values[f"new_subscriptions_{suffix}"] = (len(sold), {})
            values[f"cancellations_{suffix}"] = (len(cancelled), {})
            for key, group in ((f"sold_annual_value_{suffix}", sold), (f"cancelled_annual_value_{suffix}", cancelled)):
                known = [x.annual_value for x in group if x.annual_value is not None]
                if group and not known:
                    continue  # no value reported by source -> unavailable, never estimated
                values[key] = (_r(sum(known)), {"missing_value_count": len(group) - len(known)})
            if suffix == "mtd":
                values["net_subscriptions_mtd"] = (len(sold) - len(cancelled), {"sold": len(sold), "cancelled": len(cancelled)})

        # Assemble Metric objects with availability + goals
        goals = self._goals(company, w)
        metrics: dict[str, Metric] = {}
        for d in DEFS:
            missing = [cov[e] for e in d.requires if e not in ok]
            if missing:
                metrics[d.key] = Metric.unavailable(d.key, d.label, d.unit, d.period, "; ".join(missing))
                continue
            if d.key not in values:
                reason = {
                    "completion_rate_day": "No appointments were due in the period",
                    "avg_ticket_day": "No invoices in the period",
                }.get(d.key, "Source records do not include this value")
                metrics[d.key] = Metric.unavailable(d.key, d.label, d.unit, d.period, reason)
                continue
            val, detail = values[d.key]
            m = Metric(key=d.key, label=d.label, unit=d.unit, period=d.period, status="available",
                       value=val, detail=detail)
            m.goal = self._compare(d, val, goals, company, w)
            metrics[d.key] = m

        techs, techs_status, techs_reason = self._technicians(a_day, inv_by_appt, employees, ok, cov)
        reps, reps_status, reps_reason = self._sales_reps(subs_added, employees, w, ok, cov)
        branch_rows = self._branches(branches, inv_day, inv_mtd, a_day, subs_added, subs_cancel, w, ok)
        findings = self._findings(metrics, techs, no_inv, employees, cov, failed_pay_day, branches)

        return CompanyMetrics(
            company_slug=company.slug,
            company_name=company.name,
            metrics=metrics,
            technicians=techs,
            technicians_status=techs_status,
            technicians_reason=techs_reason,
            sales_reps=reps,
            sales_reps_status=reps_status,
            sales_reps_reason=reps_reason,
            branches=branch_rows,
            findings=findings,
            data_coverage=cov,
        )

    # ------------------------------------------------------------------ goals
    def _goals(self, company: Company, w: ReportWindow) -> dict[tuple[str, str], Goal]:
        """Company-level goals keyed by (goal_key, period). A month-specific goal beats a standing one."""
        month_start, _ = month_bounds(w.day_end)
        out: dict[tuple[str, str], Goal] = {}
        for g in self.s.scalars(
            select(Goal).where(Goal.company_id == company.id, Goal.branch_id.is_(None))
        ):
            if g.period_start not in (None, month_start):
                continue
            k = (g.metric_key, g.period)
            if k not in out or (out[k].period_start is None and g.period_start is not None):
                out[k] = g
        return out

    def _compare(self, d: MetricDef, actual: float, goals, company: Company, w: ReportWindow) -> GoalComparison | None:
        if not d.goal_key:
            return None
        period = "monthly" if d.period == "mtd" else "daily"
        g = goals.get((d.goal_key, period))
        if g is None:
            return None
        wd = company.workday_set
        if d.goal_scaling == "rate":
            expected = g.target
        elif period == "monthly":
            m0, m1 = month_bounds(w.day_end)
            total = workdays_between(m0, m1, wd) or 1
            elapsed = workdays_between(m0, w.day_end, wd)
            expected = g.target * elapsed / total
        else:
            expected = g.target * max(workdays_between(w.day_start, w.day_end, wd), 1 if w.day_start == w.day_end else 0)
        lower = d.goal_key in LOWER_BETTER or g.direction == "lower_better"
        if expected <= 0:
            attainment = 100.0 if (actual <= 0 or not lower) else 0.0
        elif lower:
            attainment = (expected / actual * 100) if actual > 0 else 100.0
        else:
            attainment = actual / expected * 100
        status = "on_track" if attainment >= 100 else "at_risk" if attainment >= PACE_BEHIND * 100 else "behind"
        return GoalComparison(
            goal_key=d.goal_key, period=period, target=_r(g.target), expected_to_date=_r(expected),
            actual=_r(actual), attainment_pct=_r(attainment), gap_to_expected=_r(actual - expected),
            direction="lower_better" if lower else "higher_better", status=status,
        )

    # ------------------------------------------------------------------ breakdowns
    def _technicians(self, a_day, inv_by_appt, employees, ok, cov):
        if "appointments" not in ok:
            return [], "unavailable", cov["appointments"]
        stats: dict[str, dict] = defaultdict(lambda: {"scheduled": 0, "completed": 0, "missed": 0, "production": 0.0})
        for a in a_day:
            t = a.technician_source_id or "unassigned"
            s = stats[t]
            s["scheduled"] += 1
            if a.status == "completed":
                s["completed"] += 1
                s["production"] += inv_by_appt.get(a.source_id, 0.0)
            elif a.status in ("pending", "no_show"):
                s["missed"] += 1
        has_prod = "invoices" in ok
        out = []
        for tid, s in stats.items():
            emp = employees.get(tid)
            due = s["completed"] + s["missed"]
            out.append({
                "technician": emp.name if emp else ("Unassigned" if tid == "unassigned" else f"Employee {tid}"),
                "scheduled": s["scheduled"],
                "completed": s["completed"],
                "missed": s["missed"],
                "completion_rate": _r(s["completed"] / due * 100) if due else None,
                "production": _r(s["production"]) if has_prod else None,
                "avg_per_stop": _r(s["production"] / s["completed"]) if has_prod and s["completed"] else None,
            })
        out.sort(key=lambda r: (r["production"] or 0, r["completed"]), reverse=True)
        reason = None if has_prod else f"Production $ unavailable - {cov['invoices']}"
        return out, ("available" if has_prod else "partial"), reason

    def _sales_reps(self, subs_added, employees, w: ReportWindow, ok, cov):
        if "subscriptions" not in ok:
            return [], "unavailable", cov["subscriptions"]
        stats: dict[str, dict] = defaultdict(lambda: {"sold_day": 0, "sold_mtd": 0, "value_day": 0.0, "value_mtd": 0.0})
        for x in subs_added:
            rep = x.sold_by_source_id or "unattributed"
            if _in(x.date_added, w.mtd_start, w.mtd_end):
                stats[rep]["sold_mtd"] += 1
                stats[rep]["value_mtd"] += x.annual_value or 0
            if _in(x.date_added, w.day_start, w.day_end):
                stats[rep]["sold_day"] += 1
                stats[rep]["value_day"] += x.annual_value or 0
        out = []
        for rid, s in stats.items():
            emp = employees.get(rid)
            out.append({
                "rep": emp.name if emp else ("Unattributed" if rid == "unattributed" else f"Employee {rid}"),
                "sold_day": s["sold_day"], "sold_mtd": s["sold_mtd"],
                "annual_value_day": _r(s["value_day"]), "annual_value_mtd": _r(s["value_mtd"]),
            })
        out.sort(key=lambda r: (r["annual_value_mtd"], r["sold_mtd"]), reverse=True)
        return out, "available", None

    def _branches(self, branches, inv_day, inv_mtd, a_day, subs_added, subs_cancel, w, ok):
        rows = []
        for bid, b in sorted(branches.items()):
            r: dict = {"branch": b.name}
            if "invoices" in ok:
                r["revenue_billed_day"] = _r(sum(i.subtotal for i in inv_day if i.branch_id == bid))
                r["revenue_billed_mtd"] = _r(sum(i.subtotal for i in inv_mtd if i.branch_id == bid))
            if "appointments" in ok:
                r["completed_day"] = sum(1 for a in a_day if a.branch_id == bid and a.status == "completed")
                r["missed_day"] = sum(1 for a in a_day if a.branch_id == bid and a.status == "pending")
            if "subscriptions" in ok:
                r["sold_mtd"] = sum(1 for x in subs_added if x.branch_id == bid and _in(x.date_added, w.mtd_start, w.mtd_end))
                r["cancelled_mtd"] = sum(1 for x in subs_cancel if x.branch_id == bid and _in(x.date_cancelled, w.mtd_start, w.mtd_end))
            rows.append(r)
        return rows

    # ------------------------------------------------------------------ findings
    def _findings(self, m: dict[str, Metric], techs, no_inv, employees, cov, failed_pay_day, branches) -> list[Finding]:
        f: list[Finding] = []

        def val(k):
            x = m.get(k)
            return x.value if x and x.status == "available" else None

        for key in ("revenue_billed_mtd", "revenue_collected_mtd", "new_subscriptions_mtd"):
            x = m.get(key)
            if x and x.goal and x.goal.status != "on_track":
                f.append(Finding(
                    "high" if x.goal.status == "behind" else "medium", "revenue" if "revenue" in key else "sales",
                    f"{x.label} at {x.goal.attainment_pct:.0f}% of goal pace",
                    {"metric": key, "actual": x.value, "expected_to_date": x.goal.expected_to_date,
                     "monthly_target": x.goal.target},
                ))

        missed, sched = val("appointments_missed_day"), val("appointments_scheduled_day")
        if missed and sched:
            rate = missed / sched
            worst = sorted((t for t in techs if t["missed"]), key=lambda t: t["missed"], reverse=True)[:3]
            f.append(Finding(
                "high" if rate > MISSED_RATE_HIGH else "medium", "operations",
                f"{int(missed)} scheduled appointment{'s' if missed != 1 else ''} not completed and not rescheduled",
                {"missed": int(missed), "scheduled": int(sched), "missed_pct": _r(rate * 100),
                 "by_technician": [{"technician": t["technician"], "missed": t["missed"]} for t in worst]},
            ))

        for t in techs:
            due = t["completed"] + t["missed"]
            if due >= TECH_MIN_SCHEDULED and t["completion_rate"] is not None and t["completion_rate"] < TECH_COMPLETION_FLOOR * 100:
                f.append(Finding("medium", "operations",
                                 f"{t['technician']} completed {t['completion_rate']:.0f}% of due stops",
                                 {"technician": t["technician"], "completed": t["completed"], "missed": t["missed"],
                                  "completion_rate": t["completion_rate"]}))

        if no_inv:
            f.append(Finding("medium", "billing",
                             f"{len(no_inv)} completed service{'s have' if len(no_inv) != 1 else ' has'} no invoice or a $0 invoice",
                             {"count": len(no_inv), "appointment_ids": [a.source_id for a in no_inv[:10]]}))

        sold, canc = val("new_subscriptions_day"), val("cancellations_day")
        if sold is not None and canc is not None and canc > sold:
            f.append(Finding("medium", "retention", "Cancellations exceeded new sales in the period",
                             {"sold": int(sold), "cancelled": int(canc)}))
        net = val("net_subscriptions_mtd")
        if net is not None and net < 0:
            f.append(Finding("high", "retention", "Net subscription count is shrinking month-to-date",
                             {"net": int(net), **m["net_subscriptions_mtd"].detail}))

        if failed_pay_day:
            f.append(Finding("low", "billing", f"{len(failed_pay_day)} customer payment{'s' if len(failed_pay_day) != 1 else ''} failed",
                             {"count": len(failed_pay_day), "amount": _r(sum(p.amount for p in failed_pay_day))}))

        for entity, status in cov.items():
            if status != "ok":
                f.append(Finding("info", "data", f"Data gap: {status}", {"entity": entity}))

        order = {"high": 0, "medium": 1, "low": 2, "info": 3}
        f.sort(key=lambda x: order[x.severity])
        return f


# --------------------------------------------------------------------------- portfolio
SUMMABLE = [d.key for d in DEFS if d.unit in ("usd", "count")]


def portfolio_rollup(companies: list[CompanyMetrics]) -> dict[str, Metric]:
    """Sum company metrics. If any company lacks a metric the total is marked
    PARTIAL and names the excluded companies - it is never silently understated."""
    out: dict[str, Metric] = {}
    for key in SUMMABLE:
        d = DEF_BY_KEY[key]
        have = [c for c in companies if c.metrics[key].status == "available"]
        missing = [c.company_name for c in companies if c.metrics[key].status != "available"]
        if not have:
            out[key] = Metric.unavailable(key, d.label, d.unit, d.period, "Unavailable for every company")
            continue
        total = _r(sum(c.metrics[key].value for c in have))
        out[key] = Metric(
            key=key, label=d.label, unit=d.unit, period=d.period,
            status="partial" if missing else "available", value=total,
            reason=f"Excludes {', '.join(missing)} (data unavailable)" if missing else None,
            detail={"excluded_companies": missing} if missing else {},
        )
    return out
