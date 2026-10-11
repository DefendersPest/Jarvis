"""Deterministic SAMPLE dataset for the offline prototype.

Lets the full pipeline (ingest -> metrics -> AI -> Teams card) run before any
FieldRoutes credentials exist. Every report built from it is stamped
"SAMPLE DATA - NOT REAL" in the header. It is never used when
``JARVIS_DATA_SOURCE=fieldroutes``.

The generator is seeded per (company, branch, day), so the same day always
produces the same records no matter which window asks for it.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from jarvis.connectors.base import EntityUnsupported

_TECHS = ["Marcus Bell", "Tyler Grant", "Jose Rivera", "Dana Price", "Kevin Moore", "Andre Hill",
          "Sam Ortiz", "Chris Webb", "Luis Ramos", "Ben Carter", "Ray Foster", "Nate Jordan"]
_REPS = ["Ashley Ford", "Jordan Lake", "Brianna Cole", "Derek Shaw", "Megan Tate", "Paul Young"]
_SERVICES = [("Quarterly Pest", 129.0, 99.0, 396.0), ("Bi-Monthly Pest", 99.0, 69.0, 414.0),
             ("Lawn Care Program", 89.0, 59.0, 708.0), ("Mosquito", 79.0, 59.0, 472.0),
             ("Termite Bond", 0.0, 0.0, 225.0)]


class SampleDataSource:
    name = "sample"

    def __init__(self, company_slug: str, branches: list[str], unsupported: list[str] | None = None,
                 techs_per_branch: int = 4, reps_per_branch: int = 2):
        self.company_slug = company_slug
        self.branches = [str(b) for b in branches]
        self.unsupported = set(unsupported or [])
        self.techs_per_branch = techs_per_branch
        self.reps_per_branch = reps_per_branch

    # ------------------------------------------------------------------ helpers
    def _rng(self, *parts) -> random.Random:
        return random.Random("|".join(str(p) for p in (self.company_slug, *parts)))

    def _staff(self, office: str, kind: str) -> list[tuple[str, str]]:
        idx = self.branches.index(office)
        pool, n, base = (_TECHS, self.techs_per_branch, 100) if kind == "tech" else (_REPS, self.reps_per_branch, 500)
        offset = (idx * n + (0 if self.company_slug == "defenders" else 6)) % len(pool)
        names = [pool[(offset + i) % len(pool)] for i in range(n)]
        return [(f"{self.company_slug[:3]}{base + idx * 10 + i}", nm) for i, nm in enumerate(names)]

    def _day(self, office: str, d: date) -> dict[str, list[dict]]:
        rng = self._rng(office, d.isoformat())
        out: dict[str, list[dict]] = {k: [] for k in ("customers", "subscriptions", "appointments", "invoices", "payments")}
        workday = d.weekday() < 5 or (d.weekday() == 5 and rng.random() < 0.5)
        oid = f"{office}-{d:%Y%m%d}"

        # Sales / new customers (some online sign-ups happen on weekends too)
        for i in range(rng.randint(2, 7) if workday else rng.randint(0, 2)):
            svc, init, rec, annual = rng.choice(_SERVICES)
            rep_id, _ = rng.choice(self._staff(office, "rep"))
            cid = f"C{oid}-{i}"
            out["customers"].append({"source_id": cid, "branch_source_id": office, "status": "active",
                                     "date_added": d, "date_cancelled": None,
                                     "lead_source": rng.choice(["Google", "Referral", "Door-to-door", "Website", "Yelp"])})
            out["subscriptions"].append({"source_id": f"S{oid}-{i}", "branch_source_id": office, "customer_source_id": cid,
                                         "service_type": svc, "status": "active", "date_added": d, "date_cancelled": None,
                                         "cancellation_reason": None, "sold_by_source_id": rep_id,
                                         "initial_price": init, "recurring_price": rec, "annual_value": annual})
        # Cancellations
        for i in range(rng.randint(0, 3) if workday else rng.randint(0, 1)):
            svc, init, rec, annual = rng.choice(_SERVICES)
            cid = f"CX{oid}-{i}"
            reason = rng.choice(["Moving", "Price", "Service quality", "No longer needed", "Switched provider"])
            out["subscriptions"].append({"source_id": f"SX{oid}-{i}", "branch_source_id": office, "customer_source_id": cid,
                                         "service_type": svc, "status": "cancelled",
                                         "date_added": d - timedelta(days=rng.randint(60, 900)), "date_cancelled": d,
                                         "cancellation_reason": reason, "sold_by_source_id": None,
                                         "initial_price": init, "recurring_price": rec, "annual_value": annual})
            if rng.random() < 0.7:
                out["customers"].append({"source_id": cid, "branch_source_id": office, "status": "inactive",
                                         "date_added": d - timedelta(days=rng.randint(60, 900)), "date_cancelled": d,
                                         "lead_source": None})
        if not workday:
            return out

        # Appointments, invoices, payments
        for t_idx, (tech_id, _) in enumerate(self._staff(office, "tech")):
            # One technician per company is consistently under-performing so the report has something to find.
            weak = t_idx == len(self._staff(office, "tech")) - 1 and office == self.branches[0]
            for j in range(rng.randint(9, 15)):
                svc, init, rec, _annual = rng.choice(_SERVICES[:4])
                r = rng.random()
                missed_rate = 0.25 if weak else 0.05
                status = ("completed" if r > missed_rate + 0.06 else
                          "pending" if r > 0.06 else rng.choice(["no_show", "rescheduled", "cancelled"]))
                aid = f"A{oid}-{t_idx}-{j}"
                is_initial = rng.random() < 0.12
                out["appointments"].append({"source_id": aid, "branch_source_id": office,
                                            "customer_source_id": f"CA{oid}-{t_idx}-{j}", "subscription_source_id": None,
                                            "scheduled_date": d, "completed_date": d if status == "completed" else None,
                                            "status": status, "service_type": svc, "technician_source_id": tech_id,
                                            "is_initial": is_initial})
                if status == "completed":
                    price = (init if is_initial and init else rec) * rng.uniform(0.9, 1.25)
                    if rng.random() < 0.03:
                        price = 0.0  # a $0 completed service - an operational red flag
                    sub = round(price, 2)
                    tax = round(sub * 0.07, 2)
                    out["invoices"].append({"source_id": f"T{aid}", "branch_source_id": office,
                                            "customer_source_id": f"CA{oid}-{t_idx}-{j}", "appointment_source_id": aid,
                                            "invoice_date": d, "subtotal": sub, "tax": tax, "total": round(sub + tax, 2),
                                            "balance": 0.0 if rng.random() < 0.55 else round(sub + tax, 2)})
                    if rng.random() < 0.6:
                        out["payments"].append({"source_id": f"P{aid}", "branch_source_id": office,
                                                "customer_source_id": f"CA{oid}-{t_idx}-{j}", "payment_date": d,
                                                "amount": round((sub + tax) * rng.choice([1, 1, 1, 2, 3]), 2),
                                                "status": "successful" if rng.random() > 0.04 else "failed",
                                                "method": rng.choice(["card", "ach", "check"])})
        return out

    # ------------------------------------------------------------------ DataSource
    def fetch(self, entity: str, start: date, end: date) -> list[dict]:
        if entity in self.unsupported:
            raise EntityUnsupported(f"{entity} not available for {self.company_slug} (sample: simulated missing API permission)")
        if entity == "employees":
            rows = []
            for office in self.branches:
                rows += [{"source_id": sid, "branch_source_id": office, "name": nm, "role": "technician", "active": True}
                         for sid, nm in self._staff(office, "tech")]
                rows += [{"source_id": sid, "branch_source_id": office, "name": nm, "role": "sales", "active": True}
                         for sid, nm in self._staff(office, "rep")]
            return rows
        rows: list[dict] = []
        d = start
        while d <= end:
            for office in self.branches:
                rows.extend(self._day(office, d)[entity])
            d += timedelta(days=1)
        return rows
