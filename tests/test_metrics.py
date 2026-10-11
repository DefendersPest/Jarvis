from datetime import date

from jarvis.connectors.base import EntityUnsupported
from jarvis.db import repository as repo
from jarvis.db.models import Branch, Company, Goal, Integration
from jarvis.db.session import init_db, session_scope
from jarvis.ingestion.sync import sync_company
from jarvis.metrics.engine import MetricEngine, portfolio_rollup
from jarvis.timeutil import report_window

D = date(2026, 10, 13)  # Tuesday 13th
DAY = date(2026, 10, 12)


class FixedSource:
    name = "test"

    def __init__(self, data, unsupported=()):
        self.data, self.unsupported = data, set(unsupported)

    def fetch(self, entity, start, end):
        if entity in self.unsupported:
            raise EntityUnsupported(f"{entity} blocked")
        return [dict(r) for r in self.data.get(entity, [])]


DATA = {
    "employees": [{"source_id": "T1", "branch_source_id": "1", "name": "Tech One", "role": "technician", "active": True},
                  {"source_id": "R1", "branch_source_id": "1", "name": "Rep One", "role": "sales", "active": True}],
    "appointments": [
        {"source_id": "A1", "branch_source_id": "1", "scheduled_date": DAY, "completed_date": DAY, "status": "completed", "technician_source_id": "T1"},
        {"source_id": "A2", "branch_source_id": "1", "scheduled_date": DAY, "completed_date": DAY, "status": "completed", "technician_source_id": "T1"},
        {"source_id": "A3", "branch_source_id": "1", "scheduled_date": DAY, "status": "pending", "technician_source_id": "T1"},
        {"source_id": "A4", "branch_source_id": "1", "scheduled_date": DAY, "status": "rescheduled", "technician_source_id": "T1"},
    ],
    "invoices": [
        {"source_id": "I1", "branch_source_id": "1", "appointment_source_id": "A1", "invoice_date": DAY, "subtotal": 100.0, "tax": 7.0, "total": 107.0, "balance": 107.0},
        {"source_id": "I0", "branch_source_id": "1", "invoice_date": date(2026, 10, 2), "subtotal": 900.0, "tax": 0, "total": 900.0, "balance": 0},
    ],
    "payments": [{"source_id": "P1", "branch_source_id": "1", "payment_date": DAY, "amount": 50.0, "status": "successful"}],
    "customers": [{"source_id": "C1", "branch_source_id": "1", "status": "active", "date_added": DAY}],
    "subscriptions": [
        {"source_id": "S1", "branch_source_id": "1", "status": "active", "date_added": DAY, "sold_by_source_id": "R1", "annual_value": 400.0},
        {"source_id": "S2", "branch_source_id": "1", "status": "cancelled", "date_added": date(2025, 1, 1), "date_cancelled": DAY, "annual_value": None},
    ],
}


def _setup(url, unsupported=()):
    init_db(url)
    with session_scope(url) as s:
        c = Company(slug="acme", name="Acme Pest", workdays="0,1,2,3,4")
        s.add(c)
        s.flush()
        s.add(Branch(company_id=c.id, slug="main", name="Main", source_office_id="1"))
        s.add(Integration(company_id=c.id, kind="fieldroutes", config={}, secret_names={}))
        s.add(Goal(company_id=c.id, metric_key="revenue_billed", period="monthly", target=2200.0))
        s.flush()
        s.refresh(c)
        w = report_window(D)
        sync_company(s, FixedSource(DATA, unsupported), c, w.mtd_start, w.day_end)
        return MetricEngine(s).compute_company(c, w)


def test_values_come_from_rows(tmp_path):
    cm = _setup(f"sqlite:///{tmp_path}/m.db")
    m = cm.metrics
    assert m["revenue_billed_day"].value == 100.0
    assert m["revenue_billed_mtd"].value == 1000.0
    assert m["revenue_collected_day"].value == 50.0
    assert m["appointments_scheduled_day"].value == 4
    assert m["appointments_completed_day"].value == 2
    assert m["appointments_missed_day"].value == 1
    # completion excludes rescheduled: 2 / (2 completed + 1 missed)
    assert m["completion_rate_day"].value == 66.67
    assert m["completed_without_invoice_day"].value == 1  # A2 has no invoice
    assert m["new_subscriptions_day"].value == 1 and m["cancellations_day"].value == 1
    assert m["open_balance_mtd"].value == 107.0
    tech = cm.technicians[0]
    assert tech["technician"] == "Tech One" and tech["production"] == 100.0 and tech["missed"] == 1
    assert cm.sales_reps[0]["rep"] == "Rep One"


def test_unknown_value_is_unavailable_not_zero(tmp_path):
    cm = _setup(f"sqlite:///{tmp_path}/m.db")
    # The only cancelled subscription has no annual value in the source -> unavailable, not $0
    assert cm.metrics["cancelled_annual_value_day"].status == "unavailable"
    assert cm.metrics["cancelled_annual_value_day"].value is None


def test_goal_pacing(tmp_path):
    cm = _setup(f"sqlite:///{tmp_path}/m.db")
    g = cm.metrics["revenue_billed_mtd"].goal
    # Oct 2026 has 22 weekdays; 8 elapsed through Oct 12 -> expected 2200 * 8/22 = 800
    assert g.expected_to_date == 800.0 and g.attainment_pct == 125.0 and g.status == "on_track"
    assert cm.metrics["new_customers_mtd"].goal is None


def test_missing_permission_marks_metrics_unavailable(tmp_path):
    cm = _setup(f"sqlite:///{tmp_path}/m.db", unsupported=("payments",))
    for k in ("revenue_collected_day", "revenue_collected_mtd"):
        assert cm.metrics[k].status == "unavailable"
        assert cm.metrics[k].value is None
        assert "not available from source" in cm.metrics[k].reason
    assert cm.metrics["revenue_billed_day"].status == "available"
    assert any(f.category == "data" for f in cm.findings)


def test_portfolio_partial_is_labelled(tmp_path):
    a = _setup(f"sqlite:///{tmp_path}/a.db")
    b = _setup(f"sqlite:///{tmp_path}/b.db", unsupported=("payments",))
    b.company_name = "Other Co"
    p = portfolio_rollup([a, b])
    assert p["revenue_billed_day"].status == "available" and p["revenue_billed_day"].value == 200.0
    assert p["revenue_collected_day"].status == "partial"
    assert p["revenue_collected_day"].value == 50.0
    assert "Other Co" in p["revenue_collected_day"].reason


def test_failed_sync_is_not_reported_as_zero(tmp_path):
    url = f"sqlite:///{tmp_path}/f.db"
    init_db(url)

    class Broken(FixedSource):
        def fetch(self, entity, start, end):
            if entity == "invoices":
                raise TimeoutError("FieldRoutes timed out")
            return super().fetch(entity, start, end)

    with session_scope(url) as s:
        c = Company(slug="x", name="X", workdays="0,1,2,3,4")
        s.add(c)
        s.flush()
        s.add(Branch(company_id=c.id, slug="m", name="M", source_office_id="1"))
        s.flush()
        s.refresh(c)
        w = report_window(D)
        res = sync_company(s, Broken(DATA), c, w.mtd_start, w.day_end)
        assert res["invoices"] == "failed"
        cm = MetricEngine(s).compute_company(c, w)
        assert cm.metrics["revenue_billed_day"].status == "unavailable"
        assert "last sync failed" in cm.metrics["revenue_billed_day"].reason
        assert cm.technicians_status == "partial"
