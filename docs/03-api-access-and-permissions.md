# 3. Required API Access and Permissions

Principle: **least privilege, read-only by default, scoped to named resources**. Nothing below gives JARVIS the ability to change a customer record or contact a customer.

## 3.1 FieldRoutes (per company / per FieldRoutes instance)

| Item | What to request | Status |
|---|---|---|
| API credentials | An **API key + token** for each FieldRoutes instance (The Defenders, BugPro, and each future acquisition). Request a **read-only** or reporting role if FieldRoutes offers one. | **Needed** |
| Subdomain | The `<subdomain>.pestroutes.com` for each instance | **Needed** |
| Office IDs | The FieldRoutes `officeID` for each branch (maps to `branches.source_office_id`) | **Needed** |
| Endpoint access | Read (`search` / `get`) on: `customer`, `subscription`, `appointment`, `ticket` (invoices), `payment`, `employee`. Optional later: `office`, `serviceType`, `cancellationReason`, `route`, `note`. | **Needed** |
| API reference | FieldRoutes' current API documentation for our account (not public). Used to confirm field names and status codes. | **Needed** |
| Limits & cost | Daily or per-minute rate limits, maximum IDs per search, any API fee, and whether a bulk export or data-warehouse feed exists as an alternative for history backfill | **Ask account manager** |
| IP allow-listing | If FieldRoutes restricts API calls by IP, the Function App's outbound IPs (Phase 3 can pin these with a NAT gateway) | Ask |

**What I could verify:** FieldRoutes does not publish its API reference publicly, so no live verification has been done. The connector follows the long-standing PestRoutes conventions:

- `POST https://<subdomain>.pestroutes.com/api/<entity>/search` returns IDs.
- `/<entity>/get` returns up to 1,000 records per call.
- Authentication uses `authenticationKey` and `authenticationToken`.

Every field-name assumption is isolated in `jarvis/connectors/fieldroutes_mapping.py` and marked `VERIFY`. Before go-live, `python scripts/verify_fieldroutes.py --company defenders` checks each endpoint using our real credentials, read-only. It prints which endpoints are permitted, the actual field names, and the status codes, so the mapping can be confirmed before any number reaches the CEO.

**Guardrail in code:** `FieldRoutesClient._call()` refuses any path that is not `<entity>/search` or `<entity>/get`, before a request is sent. Tests cover this (`tests/test_fieldroutes.py`). Credentials go in the POST body, never the URL, so they can't appear in proxy logs.

## 3.2 Microsoft 365 / Microsoft Graph

**Phase 1 needs no Graph permissions.** Delivery uses a Teams **Workflows** webhook created by a Teams member in the target channel or chat:

1. In the target Teams channel (or group chat), open **Workflows**.
2. Choose **"Post to a channel when a webhook request is received"** (or the chat variant).
3. Copy the URL it generates.
4. Store the URL in Key Vault as `teams-ceo-report-webhook`.

Use a private channel for testing first. Create a second workflow for an IT alerts channel and store it as `teams-ops-alert-webhook`.

Later phases use a single **JARVIS** app registration in Entra ID. A Global Administrator grants admin consent per phase, and each permission is restricted to specific resources:

| Phase | Capability | Permission (type) | Scoping / restriction |
|---|---|---|---|
| 2 | Archive each report to SharePoint | `Sites.Selected` (Application) | Grant write on the **JARVIS Reports** site only, via `POST /sites/{id}/permissions` |
| 2 | Two-way Teams bot | Azure Bot registration + Teams app manifest (no Graph scope needed for proactive messages to installed scopes) | App installed only in the CEO chat and leadership team |
| 2 | Power BI dataset refresh / embed | Service principal in a security group allowed by the Power BI tenant setting "Service principals can use Fabric APIs"; member of the JARVIS workspace only | Workspace-level |
| 3 | Send summary e-mail as `jarvis@defenderspest.com` | `Mail.Send` (Application) | Exchange **RBAC for Applications** scoped to that one mailbox (otherwise it could send as anyone) |
| 4 | Executive calendar & tasks | `Calendars.ReadWrite`, `Tasks.ReadWrite` (Delegated, signed in by the executive) **or** Application scoped by RBAC for Applications to executive mailboxes | Only executive mailboxes; actions drafted and approved |
| 4 | Employee onboarding automation | `User.ReadWrite.All`, `GroupMember.ReadWrite.All` (Application) | Approval workflow required. Highest-risk permissions, so deferred and reviewed separately. |

## 3.3 AI provider

| Option | What's needed | Notes |
|---|---|---|
| **Anthropic API** (default) | An Anthropic organization and a workspace "JARVIS" with a **monthly spend limit**. An API key stored in Key Vault as `anthropic-api-key`. | Enables server-side refusal fallback. Data handling follows the commercial terms you agree to, so review data retention options with Anthropic. |
| Claude in Microsoft Foundry | A Foundry resource with a Claude deployment. Store its key as `foundry-api-key` and set `JARVIS_AI_PROVIDER=foundry` and `JARVIS_FOUNDRY_RESOURCE`. | Billing on the Azure invoice through Microsoft Marketplace |

What the AI receives: **aggregated metrics only**, plus employee and branch names for technician and sales tables. No customer names, addresses, phone numbers, e-mails or payment details are stored in JARVIS, so none can be sent.

## 3.4 Azure roles

| Who | Role | Scope |
|---|---|---|
| Function App managed identity | Key Vault Secrets User | JARVIS Key Vault |
| Function App managed identity | Storage Blob Data Owner, Queue Data Contributor, Table Data Contributor | JARVIS storage account |
| Function App managed identity | `db_datareader`, `db_datawriter` (DDL only during setup) | `jarvis` database (`infra/post-deploy.sql`) |
| "JARVIS SQL Admins" Entra group (2 people, MFA) | SQL Entra admin | SQL server |
| "JARVIS Admins" Entra group | Key Vault Secrets Officer, Contributor | JARVIS resource group |
| Power BI report authors group | `db_datareader` | `jarvis` database |
