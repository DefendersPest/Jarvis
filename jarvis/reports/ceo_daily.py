"""Daily CEO Intelligence Report - end-to-end orchestration.

    sync each company (read-only) -> compute metrics -> roll up portfolio
    -> AI narrative (grounded) -> render -> persist -> deliver (or dry run)

Idempotent per report date: a report already delivered for a date is not sent
again unless ``force=True``. Safe to retry: every step can be re-run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import select

from jarvis.ai.analyst import Analyst
from jarvis.config import Settings
from jarvis.db import repository as repo
from jarvis.db.models import AgentFinding, MetricSnapshot, ReportRun, utcnow
from jarvis.db.session import init_db, session_scope
from jarvis.delivery import render, teams
from jarvis.ingestion.sync import build_source, sync_company
from jarvis.logging_setup import log_event
from jarvis.metrics.engine import MetricEngine, portfolio_rollup
from jarvis.metrics.types import CompanyMetrics, Metric
from jarvis.secrets import SecretProvider
from jarvis.timeutil import local_now, report_window

log = logging.getLogger(__name__)

REPORT_TYPE = "ceo_daily"
AGENT_KEY = "ceo_daily_report"


@dataclass
class ReportResult:
    run_id: int
    status: str
    report_date: date
    skipped: bool = False
    outputs: list[str] = field(default_factory=list)
    narrative_source: str = ""
    errors: list[str] = field(default_factory=list)


def build_facts(window, companies: list[CompanyMetrics], portfolio: dict[str, Metric], sample: bool) -> dict:
    return {
        "report": REPORT_TYPE,
        "sample_data": sample,
        "period": {
            "label": window.label,
            "day_start": window.day_start.isoformat(),
            "day_end": window.day_end.isoformat(),
            "mtd_start": window.mtd_start.isoformat(),
            "mtd_end": window.mtd_end.isoformat(),
            "covers_weekend": window.is_multi_day,
        },
        "portfolio": {"metrics": {k: m.to_dict() for k, m in portfolio.items()}},
        "companies": [c.to_dict() for c in companies],
    }


def run_ceo_report(
    settings: Settings,
    run_date: date | None = None,
    force: bool = False,
    skip_sync: bool = False,
) -> ReportResult:
    secrets = SecretProvider(settings)
    if settings.database_url.startswith("sqlite") or settings.env == "local":
        init_db(settings.database_url)
    run_date = run_date or local_now(settings.timezone).date()
    window = report_window(run_date)
    sample = settings.data_source == "sample"
    scope = "portfolio"

    with session_scope(settings.database_url) as s:
        if settings.env == "local" and Path(settings.tenants_file).exists():
            repo.sync_tenants_from_yaml(s, settings.tenants_file)

        run = s.scalar(select(ReportRun).where(
            ReportRun.report_type == REPORT_TYPE, ReportRun.scope == scope, ReportRun.report_date == run_date))
        if run and run.status == "delivered" and not force:
            log.info("CEO report for %s already delivered (run %s); skipping", run_date, run.id)
            return ReportResult(run.id, run.status, run_date, skipped=True)
        if run is None:
            run = ReportRun(report_type=REPORT_TYPE, scope=scope, report_date=run_date,
                            window_start=window.day_start, window_end=window.day_end,
                            status="running", data_source=settings.data_source)
            s.add(run)
        run.status, run.error, run.attempts = "running", None, (run.attempts or 0) + 1
        s.commit()
        run_id = run.id

    result = ReportResult(run_id=run_id, status="running", report_date=run_date)
    try:
        # 1. Sync + compute per company
        company_metrics: list[CompanyMetrics] = []
        with session_scope(settings.database_url) as s:
            engine = MetricEngine(s)
            for company in repo.active_companies(s):
                if not skip_sync:
                    try:
                        source = build_source(settings, secrets, s, company)
                        sync_company(s, source, company, min(window.day_start, window.mtd_start), window.day_end)
                    except Exception as exc:
                        # Credentials missing, source down... the company still appears, with every
                        # dependent metric marked UNAVAILABLE and the reason recorded.
                        log.exception("Could not sync %s", company.slug)
                        result.errors.append(f"{company.slug}: {type(exc).__name__}: {exc}")
                        for entity in ("employees", "customers", "subscriptions", "appointments", "invoices", "payments"):
                            r = repo.start_sync(s, company.id, entity, min(window.day_start, window.mtd_start), window.day_end)
                            repo.finish_sync(s, r, "failed", error=f"{type(exc).__name__}: {exc}")
                        s.commit()
                company_metrics.append(engine.compute_company(company, window))
        if not company_metrics:
            raise RuntimeError("No active companies configured")

        portfolio = portfolio_rollup(company_metrics)
        facts = build_facts(window, company_metrics, portfolio, sample)

        # 2. Narrative
        analysis = Analyst(settings, secrets).write(facts)
        narrative = analysis.narrative.model_dump()
        result.narrative_source = (
            f"AI ({analysis.model}), numbers verified against source data" if analysis.ai_used
            else f"rule-based ({analysis.note})"
        )

        # 3. Render
        meta = {"generated_at": local_now(settings.timezone).strftime("%Y-%m-%d %H:%M %Z"),
                "narrative_source": result.narrative_source, "run_id": run_id}
        markdown = render.to_markdown(facts, narrative, meta)
        card = render.to_adaptive_card(facts, narrative, meta)

        # 4. Persist
        with session_scope(settings.database_url) as s:
            run = s.get(ReportRun, run_id)
            run.facts, run.narrative, run.rendered_markdown = facts, narrative, markdown
            run.ai_used, run.ai_model = analysis.ai_used, analysis.model
            run.status = "generated"
            _persist_snapshots(s, run, company_metrics, portfolio, window)

        # 5. Deliver
        stem = f"ceo-report-{run_date.isoformat()}"
        if settings.dry_run:
            paths = teams.write_dry_run(settings.output_path, stem, markdown, render.to_html(markdown), card)
            result.outputs = [str(p) for p in paths]
            status, destination = "generated", f"dry-run:{settings.output_path}"
        else:
            webhook = secrets.get(settings.teams_webhook_secret)
            teams.post_card(webhook, card)
            status, destination = "delivered", "teams:ceo-report"
        with session_scope(settings.database_url) as s:
            run = s.get(ReportRun, run_id)
            run.status, run.destination = status, destination
            if status == "delivered":
                run.delivered_at = utcnow()
            repo.audit(s, AGENT_KEY, "report.deliver" if status == "delivered" else "report.dry_run",
                       destination, {"run_id": run_id, "report_date": run_date.isoformat()})
        result.status = status
        log_event(log, "ceo_report.done", run_id=run_id, status=status, narrative=result.narrative_source,
                  errors=result.errors)
        return result

    except Exception as exc:
        log.exception("CEO report run %s failed", run_id)
        with session_scope(settings.database_url) as s:
            run = s.get(ReportRun, run_id)
            run.status, run.error = "failed", f"{type(exc).__name__}: {exc}"[:4000]
        _alert_ops(settings, secrets, f"JARVIS CEO report for {run_date} failed: {type(exc).__name__}: {exc}")
        raise


def _persist_snapshots(s, run: ReportRun, companies: list[CompanyMetrics], portfolio: dict[str, Metric], window) -> None:
    from jarvis.db.models import Company

    slugs = {c.slug: c.id for c in s.scalars(select(Company))}

    def add(company_id, m: Metric):
        start = window.day_start if m.period == "day" else window.mtd_start
        s.add(MetricSnapshot(report_run_id=run.id, company_id=company_id, metric_key=m.key,
                             period_start=start, period_end=window.day_end, value=m.value,
                             status=m.status, detail={"reason": m.reason, "goal": m.goal.__dict__ if m.goal else None,
                                                      **(m.detail or {})}))

    for c in companies:
        for m in c.metrics.values():
            add(slugs[c.company_slug], m)
        for f in c.findings:
            s.add(AgentFinding(agent_key=AGENT_KEY, report_run_id=run.id, company_id=slugs[c.company_slug],
                               severity=f.severity, category=f.category, title=f.title[:300], detail=f.detail))
    for m in portfolio.values():
        add(None, m)


def _alert_ops(settings: Settings, secrets: SecretProvider, message: str) -> None:
    """Best-effort failure alert to the IT/ops Teams channel (never raises)."""
    if settings.dry_run:
        log.error("OPS ALERT (dry run, not sent): %s", message)
        return
    try:
        url = secrets.get_optional(settings.ops_alert_webhook_secret)
        if url:
            teams.post_card(url, {"type": "AdaptiveCard", "version": "1.4", "body": [
                {"type": "TextBlock", "text": "JARVIS alert", "weight": "Bolder", "color": "Attention"},
                {"type": "TextBlock", "text": message[:2000], "wrap": True}]})
    except Exception:
        log.exception("Failed to send ops alert")
