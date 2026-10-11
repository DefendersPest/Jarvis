"""JARVIS command line.

    python -m jarvis.cli init-db
    python -m jarvis.cli tenants sync --file config/tenants.example.yaml
    python -m jarvis.cli report --date 2026-10-12            # dry run (default)
    python -m jarvis.cli report --date 2026-10-12 --deliver  # post to Teams (needs approval + webhook secret)
    python -m jarvis.cli schema --dialect mssql > db/schema.sql
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from datetime import date

from jarvis.config import load_settings
from jarvis.logging_setup import configure_logging


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jarvis")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    t = sub.add_parser("tenants")
    t.add_argument("action", choices=["sync"])
    t.add_argument("--file", default=None)
    r = sub.add_parser("report")
    r.add_argument("--date", help="Run date (report covers the prior business period). Default: today")
    r.add_argument("--force", action="store_true", help="Re-run even if already delivered")
    r.add_argument("--deliver", action="store_true", help="Actually post to Teams (otherwise dry run)")
    r.add_argument("--source", choices=["sample", "fieldroutes"], help="Override JARVIS_DATA_SOURCE")
    r.add_argument("--no-ai", action="store_true", help="Use the rule-based narrative only")
    sc = sub.add_parser("schema")
    sc.add_argument("--dialect", default="mssql", choices=["mssql", "postgresql", "sqlite"])
    args = p.parse_args(argv)

    configure_logging()
    settings = load_settings()

    if args.cmd == "schema":
        from sqlalchemy import create_mock_engine
        from sqlalchemy.schema import CreateIndex, CreateTable

        from jarvis.db.models import Base

        url = {"mssql": "mssql+pyodbc://", "postgresql": "postgresql://", "sqlite": "sqlite://"}[args.dialect]
        engine = create_mock_engine(url, lambda *a, **k: None)
        print("-- JARVIS central database schema (generated from jarvis/db/models.py)\n")
        for table in Base.metadata.sorted_tables:
            print(str(CreateTable(table).compile(dialect=engine.dialect)).strip() + ";\n")
            for idx in table.indexes:
                print(str(CreateIndex(idx).compile(dialect=engine.dialect)).strip() + ";\n")
        return 0

    from jarvis.db.session import init_db, session_scope

    if args.cmd == "init-db":
        init_db(settings.database_url)
        print(f"Database ready: {settings.database_url.split('?')[0]}")
        return 0

    if args.cmd == "tenants":
        from jarvis.db.repository import sync_tenants_from_yaml

        init_db(settings.database_url)
        with session_scope(settings.database_url) as s:
            companies = sync_tenants_from_yaml(s, args.file or settings.tenants_file)
            print("Synced companies:", ", ".join(c.slug for c in companies))
        return 0

    if args.cmd == "report":
        from jarvis.reports.ceo_daily import run_ceo_report

        overrides = {}
        if args.source:
            overrides["data_source"] = args.source
        if args.no_ai:
            overrides["ai_provider"] = "none"
        if args.deliver:
            overrides["dry_run"] = False
        settings = dataclasses.replace(settings, **overrides)
        run_date = date.fromisoformat(args.date) if args.date else None
        res = run_ceo_report(settings, run_date=run_date, force=args.force)
        print(f"Run {res.run_id}: {res.status}{' (skipped - already delivered)' if res.skipped else ''}")
        print(f"Narrative: {res.narrative_source}")
        for o in res.outputs:
            print("  wrote", o)
        for e in res.errors:
            print("  WARNING", e)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
