"""Read-only FieldRoutes capability check - run this BEFORE go-live.

For one company it calls each */search and */get endpoint JARVIS uses, over a
small recent window, and prints:
  * which entities the API key can read (and which are denied),
  * the actual field names returned (to confirm jarvis/connectors/fieldroutes_mapping.py),
  * the distinct status codes seen (to confirm the status maps).
It never prints customer-identifying values, and it makes no write calls - the
client refuses anything other than search/get.

Usage (credentials come from Key Vault or JARVIS_SECRET_* env vars):
    python scripts/verify_fieldroutes.py --company defenders --days 3
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.config import load_settings  # noqa: E402
from jarvis.connectors.base import EntityUnsupported  # noqa: E402
from jarvis.connectors.fieldroutes import FieldRoutesClient  # noqa: E402
from jarvis.connectors.fieldroutes_mapping import DATE_FILTERS, ENDPOINTS  # noqa: E402
from jarvis.secrets import SecretProvider  # noqa: E402

STATUS_FIELDS = {"appointments": ["status"], "customers": ["status"], "subscriptions": ["active"],
                 "payments": ["status", "paymentMethod"], "employees": ["type", "active"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", required=True)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--subdomain", help="Override subdomain from tenants file")
    args = ap.parse_args()

    import yaml

    settings = load_settings()
    tenants = yaml.safe_load(Path(settings.tenants_file).read_text())
    company = next(c for c in tenants["companies"] if c["slug"] == args.company)
    fr = company["integrations"]["fieldroutes"]
    secrets = SecretProvider(settings)
    client = FieldRoutesClient(
        subdomain=args.subdomain or fr["config"]["subdomain"],
        auth_key=secrets.get(fr["secret_names"]["auth_key"]),
        auth_token=secrets.get(fr["secret_names"]["auth_token"]),
        office_ids=[str(b["source_office_id"]) for b in company.get("branches", [])],
    )
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=args.days - 1)
    print(f"FieldRoutes capability check for {company['name']} ({start}..{end})\n")
    ok = True
    for entity, (segment, _, _) in ENDPOINTS.items():
        between = {"operator": "BETWEEN", "value": [start.isoformat(), end.isoformat()]}
        filt = {DATE_FILTERS[entity][0]: between} if DATE_FILTERS[entity] else {}
        try:
            ids = client.search_ids(entity, filt)
            records = client.get_records(entity, ids[:25])
        except EntityUnsupported as exc:
            print(f"[DENIED] {segment}: {exc}")
            ok = False
            continue
        except Exception as exc:
            print(f"[ERROR ] {segment}: {type(exc).__name__}: {exc}")
            ok = False
            continue
        fields = sorted({k for r in records for k in r.keys()})
        print(f"[  OK  ] {segment}: {len(ids)} ids in window; sampled {len(records)}")
        print(f"         fields: {', '.join(fields) if fields else '(no records in window)'}")
        for f in STATUS_FIELDS.get(entity, []):
            counts = Counter(str(r.get(f)) for r in records)
            if counts:
                print(f"         distinct {f}: {dict(counts)}")
    print("\nNext: compare these fields with jarvis/connectors/fieldroutes_mapping.py (lines marked VERIFY).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
