# 4. Phased Implementation Plan

Each phase ends with an explicit approval gate. Nothing is deployed to production, connected to live FieldRoutes data, or sent to a Teams audience until the President (or a delegate) approves that gate.

## Phase 0 - Prototype (complete, this repository)

- [x] Architecture, cost estimate, permissions, database design, security plan (`docs/`)
- [x] Working end-to-end prototype: ingest, metrics, AI narrative with grounding check, Teams Adaptive Card. Runs offline on a clearly labeled sample dataset.
- [x] Read-only FieldRoutes connector with a write-blocking guard; capability-check script
- [x] Infrastructure as code (`infra/main.bicep`, validated with `bicep build`), **not deployed**
- [x] Automated tests (25) and CI workflow

## Phase 1 - Daily CEO report live for The Defenders (about 3 weeks)

**Week 1 - access and definitions**

1. Approve the Azure subscription and resource group, and the $150/month budget.
2. Request FieldRoutes API credentials, the API reference, and the office ID list (see `docs/07-credentials-and-go-live.md`).
3. Create the Anthropic workspace with a spend limit (or a Foundry deployment).
4. Create two Teams workflows: a **test** channel for now, and the CEO channel or chat later.
5. Confirm metric definitions (`docs/metric-definitions.md`) and set real goals in `config/tenants.yaml`.

**Week 2 - deploy to dev and verify data**

1. **Gate: approve infrastructure deployment.** Run `az deployment group create ...` and `infra/post-deploy.sql`.
2. Admins put secrets into Key Vault themselves (never via chat or e-mail).
3. Run `scripts/verify_fieldroutes.py`, fix anything marked `VERIFY` in the field mapping, and re-run the tests.
4. Backfill 60-90 days of history so pacing and trends have context.

**Week 3 - parallel run and reconciliation**

1. Set `JARVIS_DATA_SOURCE=fieldroutes` and `JARVIS_DRY_RUN=false`, with the webhook pointing to the **test channel**.
2. Each morning, compare JARVIS figures with FieldRoutes' own reports. Acceptance criteria:
   - Revenue within ±0.5%.
   - Exact counts for appointments, new customers and cancellations.
   - Every difference explained.
3. **Gate: go-live approval.** Switch the webhook secret to the CEO channel.

**Exit criteria:**

- 10 consecutive weekday reports delivered by 6:05 AM.
- Zero unexplained metric differences.
- Alerts tested (simulate a failure).

## Phase 2 - Multi-company and self-service (month 2)

- Onboard **BugPro**: add a tenants YAML block, its credentials, a verify run, and a parallel run. This is the proof that adding a company needs no rebuild.
- Portfolio view: per-company sections plus totals (already in the report).
- Power BI semantic model on the JARVIS database (metric_snapshots, operational tables). Replace manual spreadsheets.
- Archive every report to a SharePoint "JARVIS Reports" site (`Sites.Selected`).
- Teams bot (Azure Bot): ask JARVIS questions; answers use read-only queries with the same grounding rule.
- Weekly and month-end variants of the CEO report.

## Phase 3 - First agents and hardening (months 3-4)

- **Technician performance monitor**: weekly scorecards, completion rate, production per hour, callbacks.
- **Customer retention agent**: daily at-risk list (missed services, failed payments, recent complaints, downgrades) posted for the office team. It makes no outreach; humans call.
- **Acquisition integration monitor**: each acquired company's KPIs against its pre-acquisition baseline.
- Hardening:
  - Private endpoints for SQL and Key Vault, VNet integration, NAT gateway for a fixed outbound IP.
  - Separate dev and prod environments, and a CI/CD deploy workflow with manual approval.

## Phase 4 - Expansion (months 4-6+)

- Cross-selling agent (pest customers without lawn or mosquito services; recommendations go to sales reps).
- Financial analysis (AR aging, margin by service line; adds an accounting-system connector).
- Marketing performance (lead source to revenue; adds ad-platform and call-tracking connectors).
- Executive scheduling and task management (Graph calendar and Planner, with drafts approved by the executive).
- Employee onboarding automation (accounts, Teams, SharePoint, checklists; HR approval workflow).

## Approval gates summary

| Gate | Who approves | What it unlocks |
|---|---|---|
| G1 Infrastructure | President | Create Azure resources (cost begins) |
| G2 Live data | President + FieldRoutes admin | Read-only FieldRoutes access from Azure |
| G3 Go-live | President | Report delivered to the CEO channel |
| G4 Each new agent | President | Agent enabled in the `agents` table with its permission list |
| G5 Any write-capable permission | President + IT | Separate design review; not planned |
