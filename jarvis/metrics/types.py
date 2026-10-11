"""Metric value objects. A metric is either AVAILABLE with a value computed
from source rows, or UNAVAILABLE with a reason. There is no third option and no
default of zero."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Status = Literal["available", "unavailable", "partial"]
Unit = Literal["usd", "count", "pct", "usd_avg"]


@dataclass
class GoalComparison:
    goal_key: str
    period: str                 # daily | monthly
    target: float               # full target for the period
    expected_to_date: float     # target scaled to the window (pacing)
    actual: float
    attainment_pct: float       # actual / expected_to_date * 100 (inverted for lower_better)
    gap_to_expected: float      # actual - expected_to_date
    direction: str
    status: str                 # on_track | at_risk | behind


@dataclass
class Metric:
    key: str
    label: str
    unit: Unit
    period: str                 # day | mtd
    status: Status
    value: float | None = None
    reason: str | None = None
    goal: GoalComparison | None = None
    detail: dict = field(default_factory=dict)

    @classmethod
    def unavailable(cls, key: str, label: str, unit: Unit, period: str, reason: str) -> "Metric":
        return cls(key=key, label=label, unit=unit, period=period, status="unavailable", reason=reason)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Finding:
    severity: str               # high | medium | low | info
    category: str               # revenue | operations | sales | retention | billing | data
    title: str
    detail: dict = field(default_factory=dict)
    branch: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CompanyMetrics:
    company_slug: str
    company_name: str
    metrics: dict[str, Metric]
    technicians: list[dict]
    technicians_status: Status
    technicians_reason: str | None
    sales_reps: list[dict]
    sales_reps_status: Status
    sales_reps_reason: str | None
    branches: list[dict]
    findings: list[Finding]
    data_coverage: dict[str, str]

    def to_dict(self) -> dict:
        return {
            "company_slug": self.company_slug,
            "company_name": self.company_name,
            "metrics": {k: m.to_dict() for k, m in self.metrics.items()},
            "technicians": {"status": self.technicians_status, "reason": self.technicians_reason, "rows": self.technicians},
            "sales_reps": {"status": self.sales_reps_status, "reason": self.sales_reps_reason, "rows": self.sales_reps},
            "branches": self.branches,
            "findings": [f.to_dict() for f in self.findings],
            "data_coverage": self.data_coverage,
        }
