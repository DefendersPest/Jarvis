"""Pull source data for a window into the central database."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from jarvis.config import Settings
from jarvis.connectors.base import ENTITIES, DataSource, EntityUnsupported
from jarvis.connectors.fieldroutes import FieldRoutesClient
from jarvis.connectors.sample_data import SampleDataSource
from jarvis.db import repository as repo
from jarvis.db.models import Appointment, Company, Customer, Employee, Invoice, Payment, Subscription
from jarvis.logging_setup import log_event
from jarvis.secrets import SecretProvider

log = logging.getLogger(__name__)

MODELS = {
    "employees": Employee,
    "customers": Customer,
    "subscriptions": Subscription,
    "appointments": Appointment,
    "invoices": Invoice,
    "payments": Payment,
}


class NoSourceConfigured(RuntimeError):
    pass


def build_source(settings: Settings, secrets: SecretProvider, session: Session, company: Company) -> DataSource:
    integ = repo.integration_for(session, company.id, "fieldroutes")
    if integ is None:
        raise NoSourceConfigured(f"No enabled FieldRoutes integration for {company.slug}")
    offices = [b.source_office_id for b in company.branches if b.source_office_id]
    if settings.data_source == "sample":
        return SampleDataSource(
            company.slug,
            offices,
            unsupported=integ.config.get("sample_unsupported", []),
            techs_per_branch=integ.config.get("sample_techs_per_branch", 4),
        )
    if settings.data_source == "fieldroutes":
        return FieldRoutesClient(
            subdomain=integ.config["subdomain"],
            auth_key=secrets.get(integ.secret_names["auth_key"]),
            auth_token=secrets.get(integ.secret_names["auth_token"]),
            office_ids=offices,
            timeout=settings.http_timeout_seconds,
        )
    raise ValueError(f"Unknown JARVIS_DATA_SOURCE '{settings.data_source}'")


def sync_company(session: Session, source: DataSource, company: Company, start: date, end: date) -> dict[str, str]:
    """Sync every entity for one company. One entity failing never stops the
    others; its failure is recorded so dependent metrics show as unavailable."""
    branches = repo.branch_map(session, company.id)
    results: dict[str, str] = {}
    for entity in ENTITIES:
        run = repo.start_sync(session, company.id, entity, start, end)
        try:
            rows = source.fetch(entity, start, end)
            unknown_offices = set()
            for r in rows:
                office = r.pop("branch_source_id", None)
                branch = branches.get(office) if office else None
                if office and branch is None:
                    unknown_offices.add(office)
                r["branch_id"] = branch.id if branch else None
            n = repo.upsert_rows(session, MODELS[entity], company.id, rows, source_system=source.name)
            repo.finish_sync(session, run, "succeeded", records=n)
            results[entity] = f"ok ({n})"
            if unknown_offices:
                log.warning("%s/%s: rows for unmapped offices %s", company.slug, entity, sorted(unknown_offices))
        except EntityUnsupported as exc:
            repo.finish_sync(session, run, "unsupported", error=str(exc))
            results[entity] = "unsupported"
        except Exception as exc:  # recorded, surfaced in the report and in App Insights
            log.exception("Sync failed: %s/%s", company.slug, entity)
            repo.finish_sync(session, run, "failed", error=f"{type(exc).__name__}: {exc}")
            results[entity] = "failed"
        session.commit()
    log_event(log, "sync.company", company=company.slug, start=start, end=end, results=results)
    return results
