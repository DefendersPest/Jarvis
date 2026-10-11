# JARVIS - The Defenders AI Operating System

JARVIS is a cloud-based AI operating system for The Defenders and the pest control companies it acquires. It runs around the clock in Microsoft Azure; nobody's PC has to stay on. It collects business data (read-only), keeps a central multi-company history, computes performance metrics, finds problems, recommends actions, and reports through Microsoft Teams.

**First project:** the **Daily CEO Intelligence Report**, delivered every weekday at 6:00 AM Eastern.

> **Status: prototype, not deployed.**
> - The full pipeline runs today on a clearly labeled sample dataset.
> - Nothing has been deployed to Azure.
> - Nothing connects to live FieldRoutes data.
> - Nothing is posted to Teams.
>
> Each of those steps waits for approval (see the [implementation plan](docs/04-implementation-plan.md)).

## Documents

| # | Deliverable | File |
|---|---|---|
| 1 | System architecture | [docs/01-architecture.md](docs/01-architecture.md) |
| 2 | Required software, Azure services, monthly costs | [docs/02-services-and-costs.md](docs/02-services-and-costs.md) |
| 3 | API access and permissions | [docs/03-api-access-and-permissions.md](docs/03-api-access-and-permissions.md) |
| 4 | Phased implementation plan | [docs/04-implementation-plan.md](docs/04-implementation-plan.md) |
| 5 | Database structure | [docs/05-database-design.md](docs/05-database-design.md), [db/schema.sql](db/schema.sql) |
| 6 | Security and data protection | [docs/06-security.md](docs/06-security.md) |
| 7 | Credentials request and go-live checklist | [docs/07-credentials-and-go-live.md](docs/07-credentials-and-go-live.md) |
| 8 | Working prototype of the Daily CEO report | this repo; sample output in [docs/sample-output/](docs/sample-output/) |
| - | Metric definitions (for sign-off) | [docs/metric-definitions.md](docs/metric-definitions.md) |

## How the CEO report works

1. **Sync (read-only).** For each active company, JARVIS pulls customers, subscriptions, appointments, invoices, payments and employees from FieldRoutes into Azure SQL. The client cannot call anything except `search` and `get`.
2. **Compute.** Deterministic Python calculates:
   - daily and month-to-date revenue (billed and collected);
   - technician production;
   - new customers, sales by rep, and cancellations;
   - missed and no-show appointments, plus unbilled completed work;
   - pace against goals.

   If a data feed failed or isn't permitted, its metrics are marked **UNAVAILABLE** with the reason. They are never shown as zero.
3. **Explain.** Claude writes the headline, a summary of under 110 words, and **the three most important actions**, using only the computed facts. Code then checks that every number in the AI's text exists in the facts. If any doesn't, the draft is rejected, and a rule-based summary is used instead.
4. **Deliver.** An Adaptive Card goes to a Teams channel or chat. Dry-run mode writes Markdown, HTML and card JSON files instead. Every run is stored with its exact facts for later review.

## Run the prototype locally

```bash
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

# Sample data, dry run, rule-based narrative (no keys needed)
python -m jarvis.cli report --date 2026-10-09 --no-ai
open out/ceo-report-2026-10-09.html

# With the AI narrative (needs an Anthropic API key in your environment)
export ANTHROPIC_API_KEY=...        # local testing only; production uses Key Vault
python -m jarvis.cli report --date 2026-10-09 --force

python -m pytest -q                 # 26 tests
```

Monday's report covers Friday through Sunday, for example `--date 2026-10-12`. BugPro is set up in the sample to simulate an API key without payments access, which shows how unavailable metrics are reported.

## Repository layout

```
function_app.py            Azure Functions: weekday timer (6 AM ET, DST-safe), manual HTTP trigger, health
jarvis/
  config.py, secrets.py    Settings; Key Vault secret access via managed identity
  connectors/              FieldRoutes read-only client, field mapping (VERIFY items), sample data
  ingestion/sync.py        Per-company, per-entity sync with failure isolation
  db/                      SQLAlchemy models (multi-company), sessions (Entra auth to Azure SQL), repository
  metrics/                 Deterministic metric engine, goals and pacing, issue rules, portfolio roll-up
  ai/                      Claude analyst (structured output), number-grounding check, rule-based fallback
  delivery/                Markdown/HTML/Adaptive Card rendering, Teams webhook
  reports/ceo_daily.py     End-to-end orchestration, idempotency, persistence, alerts
  agents/base.py           Agent contract and permissions for future agents
config/tenants.example.yaml  Companies, branches, integrations, goals, agents
infra/                     Bicep (Functions Flex, Azure SQL, Key Vault, App Insights, alerts, budget)
scripts/verify_fieldroutes.py  Read-only API capability check to run before go-live
tests/                     Unit and end-to-end tests
```

## Ground rules built into the code

- **Read-only:** no writes to FieldRoutes or any customer record (enforced in the connector).
- **No customer communications:** the system has no integration that contacts customers.
- **No fabricated numbers:** missing means UNAVAILABLE, and AI text is checked against the facts.
- **No deployment without approval:** the defaults are sample data and dry run, and infrastructure is deployed manually.
- **Secrets only in Key Vault:** never in code, config, logs or the database.
