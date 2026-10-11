"""Tenant configuration, idempotent upserts, and data-coverage checks."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from jarvis.db.models import (
    AgentDefinition,
    AuditLog,
    Branch,
    Company,
    Goal,
    Integration,
    SyncRun,
    utcnow,
)


# --------------------------------------------------------------------------- tenants
def sync_tenants_from_yaml(session: Session, path: str | Path) -> list[Company]:
    """Load companies, branches, integrations and goals from a YAML file.

    Re-runnable: existing rows are updated in place. This is the whole
    "add a new pest control company" procedure on the JARVIS side.
    """
    doc = yaml.safe_load(Path(path).read_text())
    companies: list[Company] = []
    for c in doc.get("companies", []):
        company = session.scalar(select(Company).where(Company.slug == c["slug"]))
        if company is None:
            company = Company(slug=c["slug"])
            session.add(company)
        company.name = c["name"]
        company.timezone = c.get("timezone", "America/New_York")
        company.workdays = ",".join(str(d) for d in c.get("workdays", [0, 1, 2, 3, 4]))
        company.active = c.get("active", True)
        company.acquired_on = c.get("acquired_on")
        session.flush()

        branch_by_slug: dict[str, Branch] = {}
        for b in c.get("branches", []):
            branch = session.scalar(
                select(Branch).where(Branch.company_id == company.id, Branch.slug == b["slug"])
            )
            if branch is None:
                branch = Branch(company_id=company.id, slug=b["slug"])
                session.add(branch)
            branch.name = b["name"]
            branch.source_office_id = str(b["source_office_id"]) if b.get("source_office_id") is not None else None
            branch.active = b.get("active", True)
            branch_by_slug[b["slug"]] = branch
        session.flush()

        for kind, spec in (c.get("integrations") or {}).items():
            integ = session.scalar(
                select(Integration).where(Integration.company_id == company.id, Integration.kind == kind)
            )
            if integ is None:
                integ = Integration(company_id=company.id, kind=kind)
                session.add(integ)
            integ.config = spec.get("config", {})
            integ.secret_names = spec.get("secret_names", {})
            integ.enabled = spec.get("enabled", True)

        for g in c.get("goals", []):
            branch_id = branch_by_slug[g["branch"]].id if g.get("branch") else None
            period_start = g.get("period_start")
            goal = session.scalar(
                select(Goal).where(
                    Goal.company_id == company.id,
                    Goal.branch_id.is_(None) if branch_id is None else Goal.branch_id == branch_id,
                    Goal.metric_key == g["metric"],
                    Goal.period == g["period"],
                    Goal.period_start.is_(None) if period_start is None else Goal.period_start == period_start,
                )
            )
            if goal is None:
                goal = Goal(
                    company_id=company.id,
                    branch_id=branch_id,
                    metric_key=g["metric"],
                    period=g["period"],
                    period_start=period_start,
                )
                session.add(goal)
            goal.target = float(g["target"])
            goal.direction = g.get("direction", "higher_better")
            goal.notes = g.get("notes")
        companies.append(company)

    for a in doc.get("agents", []):
        agent = session.scalar(select(AgentDefinition).where(AgentDefinition.key == a["key"]))
        if agent is None:
            agent = AgentDefinition(key=a["key"])
            session.add(agent)
        agent.name = a["name"]
        agent.description = a.get("description")
        agent.enabled = a.get("enabled", False)
        agent.schedule = a.get("schedule")
        agent.permissions = a.get("permissions", [])
        agent.config = a.get("config", {})

    session.flush()
    audit(session, "system", "tenants.sync", str(path), {"companies": [c.slug for c in companies]})
    return companies


def active_companies(session: Session) -> list[Company]:
    return list(session.scalars(select(Company).where(Company.active.is_(True)).order_by(Company.id)))


def branch_map(session: Session, company_id: int) -> dict[str, Branch]:
    """source_office_id -> Branch"""
    rows = session.scalars(select(Branch).where(Branch.company_id == company_id))
    return {b.source_office_id: b for b in rows if b.source_office_id is not None}


def integration_for(session: Session, company_id: int, kind: str) -> Integration | None:
    return session.scalar(
        select(Integration).where(
            Integration.company_id == company_id, Integration.kind == kind, Integration.enabled.is_(True)
        )
    )


# --------------------------------------------------------------------------- upserts
def upsert_rows(session: Session, model, company_id: int, rows: Sequence[dict], source_system: str = "fieldroutes") -> int:
    """Insert or update rows keyed on (company_id, source_system, source_id)."""
    if not rows:
        return 0
    ids = [str(r["source_id"]) for r in rows]
    existing: dict[str, object] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        for obj in session.scalars(
            select(model).where(
                model.company_id == company_id,
                model.source_system == source_system,
                model.source_id.in_(chunk),
            )
        ):
            existing[obj.source_id] = obj
    for r in rows:
        sid = str(r["source_id"])
        obj = existing.get(sid)
        if obj is None:
            obj = model(company_id=company_id, source_system=source_system, source_id=sid)
            session.add(obj)
            existing[sid] = obj
        for k, v in r.items():
            if k != "source_id":
                setattr(obj, k, v)
    session.flush()
    return len(rows)


# --------------------------------------------------------------------------- sync tracking
def start_sync(session: Session, company_id: int, entity: str, start: date, end: date) -> SyncRun:
    run = SyncRun(company_id=company_id, entity=entity, window_start=start, window_end=end, status="running")
    session.add(run)
    session.flush()
    return run


def finish_sync(session: Session, run: SyncRun, status: str, records: int = 0, error: str | None = None) -> None:
    run.status = status
    run.records = records
    run.error = (error or "")[:4000] or None
    run.finished_at = utcnow()
    session.flush()


def coverage(session: Session, company_id: int, entities: Iterable[str], start: date, end: date) -> dict[str, str]:
    """For each entity: 'ok' if a successful sync covers [start, end], else a reason."""
    out: dict[str, str] = {}
    for entity in entities:
        runs = list(
            session.scalars(
                select(SyncRun)
                .where(SyncRun.company_id == company_id, SyncRun.entity == entity)
                .order_by(SyncRun.started_at.desc())
            )
        )
        ok = any(r.status == "succeeded" and r.window_start <= start and r.window_end >= end for r in runs)
        if ok:
            out[entity] = "ok"
        elif any(r.status == "unsupported" for r in runs):
            out[entity] = f"{entity}: not available from source (no API access)"
        elif runs and runs[0].status == "failed":
            out[entity] = f"{entity}: last sync failed ({(runs[0].error or 'unknown error')[:120]})"
        else:
            out[entity] = f"{entity}: not synced for {start}..{end}"
    return out


def audit(session: Session, actor: str, action: str, target: str | None = None, detail: dict | None = None) -> None:
    session.add(AuditLog(actor=actor, action=action, target=target, detail=detail, at=utcnow()))
