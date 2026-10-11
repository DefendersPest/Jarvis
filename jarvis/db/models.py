"""Central JARVIS data model.

Multi-tenant by design: every operational row carries ``company_id`` (and
``branch_id`` where it applies). A new acquisition is a new ``companies`` row,
its ``branches`` and an ``integrations`` row - no schema change, no new code.

Operational tables keep the *source system's* identifiers (``source_id``,
``customer_source_id`` ...) instead of hard foreign keys to each other, so
entities can be ingested independently and out of order, and a re-sync is a
simple idempotent upsert on (company_id, source_system, source_id).

Data minimisation: no customer names, addresses, phone numbers, e-mails or
payment instruments are stored. Metrics do not need them.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UnicodeText,
    UniqueConstraint,
)
from sqlalchemy.dialects import mssql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


Money = Numeric(14, 2, asdecimal=False)
# NVARCHAR(MAX) on Azure SQL (TEXT/NTEXT are deprecated there), TEXT elsewhere.
LongText = UnicodeText().with_variant(mssql.NVARCHAR(None), "mssql")


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- tenancy
class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York")
    # Comma-separated weekday numbers (0=Mon) the company services customers; used for goal pacing.
    workdays: Mapped[str] = mapped_column(String(20), default="0,1,2,3,4")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    acquired_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    branches: Mapped[list[Branch]] = relationship(back_populates="company")

    @property
    def workday_set(self) -> set[int]:
        return {int(x) for x in self.workdays.split(",") if x.strip()}


class Branch(Base):
    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("company_id", "slug"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    # FieldRoutes officeID (or equivalent in another source system)
    source_office_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    company: Mapped[Company] = relationship(back_populates="branches")


class Integration(Base):
    """A connection from one company to one source system.

    ``config`` holds non-secret settings (e.g. FieldRoutes subdomain).
    ``secret_names`` maps credential roles to Key Vault secret *names* - never values.
    """

    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("company_id", "kind"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    kind: Mapped[str] = mapped_column(String(32))  # "fieldroutes", later "quickbooks", ...
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    secret_names: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


# --------------------------------------------------------------------------- operational
class _SourceRow:
    """Columns shared by every row ingested from a source system."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    source_system: Mapped[str] = mapped_column(String(32), default="fieldroutes")
    source_id: Mapped[str] = mapped_column(String(64))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Employee(_SourceRow, Base):
    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("company_id", "source_system", "source_id"),)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32), default="unknown")  # technician | sales | office | unknown
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Customer(_SourceRow, Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("company_id", "source_system", "source_id"),
        Index("ix_customers_added", "company_id", "date_added"),
        Index("ix_customers_cancelled", "company_id", "date_cancelled"),
    )
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | inactive | frozen
    date_added: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_cancelled: Mapped[date | None] = mapped_column(Date, nullable=True)
    lead_source: Mapped[str | None] = mapped_column(String(100), nullable=True)


class Subscription(_SourceRow, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("company_id", "source_system", "source_id"),
        Index("ix_subs_added", "company_id", "date_added"),
        Index("ix_subs_cancelled", "company_id", "date_cancelled"),
    )
    customer_source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | cancelled
    date_added: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_cancelled: Mapped[date | None] = mapped_column(Date, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sold_by_source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    initial_price: Mapped[float | None] = mapped_column(Money, nullable=True)
    recurring_price: Mapped[float | None] = mapped_column(Money, nullable=True)
    annual_value: Mapped[float | None] = mapped_column(Money, nullable=True)


class Appointment(_SourceRow, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        UniqueConstraint("company_id", "source_system", "source_id"),
        Index("ix_appts_date", "company_id", "scheduled_date"),
    )
    customer_source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subscription_source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scheduled_date: Mapped[date] = mapped_column(Date)
    completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Normalised: pending | completed | no_show | cancelled | rescheduled
    status: Mapped[str] = mapped_column(String(32))
    service_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    technician_source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_initial: Mapped[bool] = mapped_column(Boolean, default=False)


class Invoice(_SourceRow, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("company_id", "source_system", "source_id"),
        Index("ix_invoices_date", "company_id", "invoice_date"),
    )
    customer_source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    appointment_source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invoice_date: Mapped[date] = mapped_column(Date)
    subtotal: Mapped[float] = mapped_column(Money, default=0)
    tax: Mapped[float] = mapped_column(Money, default=0)
    total: Mapped[float] = mapped_column(Money, default=0)
    balance: Mapped[float | None] = mapped_column(Money, nullable=True)


class Payment(_SourceRow, Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("company_id", "source_system", "source_id"),
        Index("ix_payments_date", "company_id", "payment_date"),
    )
    customer_source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Money, default=0)
    status: Mapped[str] = mapped_column(String(32), default="successful")  # successful | failed | voided
    method: Mapped[str | None] = mapped_column(String(32), nullable=True)


# --------------------------------------------------------------------------- goals & analytics
class Goal(Base):
    """A target for one metric. ``branch_id`` NULL means company-wide.

    ``period`` is ``daily`` or ``monthly``. Monthly goals apply to the month
    starting ``period_start``; a NULL ``period_start`` is a standing default.
    """

    __tablename__ = "goals"
    __table_args__ = (UniqueConstraint("company_id", "branch_id", "metric_key", "period", "period_start"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    metric_key: Mapped[str] = mapped_column(String(64))
    period: Mapped[str] = mapped_column(String(16))
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    target: Mapped[float] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(16), default="higher_better")  # or lower_better
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)


class SyncRun(Base):
    """One ingestion of one entity for one company over one date window.

    Metrics only count as *available* when every entity they depend on has a
    successful SyncRun covering the window. This is how JARVIS knows the
    difference between "zero cancellations" and "we don't know".
    """

    __tablename__ = "sync_runs"
    __table_args__ = (Index("ix_sync_lookup", "company_id", "entity", "status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    entity: Mapped[str] = mapped_column(String(32))
    window_start: Mapped[date] = mapped_column(Date)
    window_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16))  # running | succeeded | failed | unsupported
    records: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(LongText, nullable=True)


class ReportRun(Base):
    """One report, idempotent per (report_type, scope, report_date)."""

    __tablename__ = "report_runs"
    __table_args__ = (UniqueConstraint("report_type", "scope", "report_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_type: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(64))  # "portfolio" or a company slug
    report_date: Mapped[date] = mapped_column(Date)
    window_start: Mapped[date] = mapped_column(Date)
    window_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16))  # running | generated | delivered | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    data_source: Mapped[str] = mapped_column(String(32))
    ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_used: Mapped[bool] = mapped_column(Boolean, default=False)
    facts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    narrative: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rendered_markdown: Mapped[str | None] = mapped_column(LongText, nullable=True)
    destination: Mapped[str | None] = mapped_column(String(200), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(LongText, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MetricSnapshot(Base):
    """Every computed metric value is persisted - this is the history Power BI
    and future agents (trend, retention, acquisition-integration) build on."""

    __tablename__ = "metric_snapshots"
    __table_args__ = (Index("ix_metric_lookup", "company_id", "metric_key", "period_end"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_run_id: Mapped[int | None] = mapped_column(ForeignKey("report_runs.id"), nullable=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)  # NULL = portfolio
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    metric_key: Mapped[str] = mapped_column(String(64))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16))  # available | unavailable
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- agent platform
class AgentDefinition(Base):
    """Registry of JARVIS agents (CEO report today; retention, cross-sell,
    technician performance, finance, acquisition integration ... later)."""

    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(LongText, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    schedule: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Explicit allow-list of what the agent may do, e.g. ["read:metrics", "post:teams"].
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class AgentFinding(Base):
    """Issues and recommendations raised by any agent, tracked to resolution."""

    __tablename__ = "agent_findings"
    __table_args__ = (Index("ix_findings_open", "company_id", "status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_key: Mapped[str] = mapped_column(String(64))
    report_run_id: Mapped[int | None] = mapped_column(ForeignKey("report_runs.id"), nullable=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    severity: Mapped[str] = mapped_column(String(16))  # high | medium | low | info
    category: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | acknowledged | resolved
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Append-only record of every outbound action (report delivered, alert sent,
    config changed). JARVIS never writes to source systems; if that ever changes
    it will be gated by approval and logged here."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str | None] = mapped_column(String(300), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
