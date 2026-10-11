# 6. Security and Data Protection Requirements

## 6.1 Non-negotiable rules (enforced in code where possible)

| Rule | How it is enforced |
|---|---|
| JARVIS never changes live customer records | The FieldRoutes client allows only `*/search` and `*/get`. Anything else raises `ReadOnlyViolation` before a request is sent (tested). No write endpoints are implemented. |
| JARVIS never contacts customers | No e-mail, SMS or voice integration toward customers exists. The agent permission list (`jarvis/agents/base.py`) has no customer-facing permission. Adding one requires a design review (gate G5). |
| No fabricated numbers | Numbers come only from the deterministic metric engine. Missing data is shown as **UNAVAILABLE** with a reason. The AI's text is checked so every number must appear in the facts; otherwise it is rejected and replaced (tested). |
| No deployment without approval | Infrastructure is code, but deployment is a manual, approved step. Defaults are `JARVIS_DRY_RUN=true` and `JARVIS_DATA_SOURCE=sample`. |
| No secrets outside Key Vault | Code, config, database (names only), logs (redaction filter) and git (`.gitignore` excludes `local.settings.json` and `.env`) contain no secrets |

## 6.2 Identity and access

- **Managed identity** for the Function App, used for Key Vault, Storage and SQL. No passwords or connection-string secrets.
- **Azure SQL Entra-only authentication.** SQL logins are disabled.
- **Least privilege** (see `docs/03-api-access-and-permissions.md`): Key Vault Secrets *User* (read only), database reader/writer, Graph permissions scoped to specific sites and mailboxes.
- Admin access through Entra groups (`JARVIS Admins`, `JARVIS SQL Admins`) of no more than 2-3 people, with **MFA and Conditional Access** required. Use Privileged Identity Management (PIM) for just-in-time elevation if licensed (Entra ID P2).
- The manual HTTP trigger requires a function key. In production, add App Service Authentication (Entra ID) so only JARVIS admins can call it.

## 6.3 Secrets management

- Store in Key Vault: FieldRoutes key and token per company, the AI API key, Teams webhook URLs (a webhook URL is a credential: anyone holding it can post).
- Soft delete (90 days) and purge protection are enabled. RBAC authorization, not access policies.
- **Rotation:**
  - FieldRoutes credentials and the AI key every 90 days, or immediately when someone with access leaves.
  - Teams webhooks are regenerated if exposed.
  - Rotation is a Key Vault update only, with no redeploy (secrets are read at run time).
- **Credential intake:** credentials are never sent by chat, e-mail or text. An admin enters them directly into Key Vault (portal or `az keyvault secret set`). See `docs/07-credentials-and-go-live.md`.

## 6.4 Data protection

- **Encryption in transit:** TLS 1.2+ enforced on SQL, Storage, Key Vault and Functions (HTTPS only, FTPS disabled).
- **Encryption at rest:** Azure SQL TDE and Storage Service Encryption (Microsoft-managed keys; customer-managed keys optional later).
- **Minimization:** no customer PII and no payment card data stored, so the database is out of PCI DSS scope. Employee names are stored for technician and sales reporting.
- **AI data handling:** only aggregated metrics plus employee and branch names are sent. Free-text fields from FieldRoutes (notes, cancellation comments) are **not** sent to the AI, which also removes a prompt-injection path. Review your Anthropic (or Foundry) data-retention terms; the AI provider is switchable by configuration.
- **Teams content:** the CEO report contains business-confidential figures. Deliver it to a private channel or chat with controlled membership.

## 6.5 Application security

- Inputs from source systems are parsed defensively; dates and money are validated.
- SQL is accessed only through SQLAlchemy's parameterized queries.
- Dependencies are pinned to major versions. Enable GitHub Dependabot alerts and secret scanning on this repository.
- The AI has **no tools**: it cannot query data, call APIs or take actions. It returns structured JSON that code validates.
- The future Teams bot will use read-only, parameterized query tools with an allow-list.

## 6.6 Logging, monitoring and audit

- Structured JSON events (`jarvis_event ...`) go to Application Insights. A redaction filter removes anything that looks like a credential.
- Alerts:
  - Any failed run.
  - No report by 7 AM Eastern on a weekday.
  - Budget at 80% and forecast 100%.
- `audit_log` records every delivery and configuration sync. `report_runs` keeps the exact facts and narrative behind every report sent, for later review.
- Recommended: enable Microsoft Defender for Cloud (free tier) recommendations on the subscription, and Key Vault diagnostic logs to Log Analytics.

## 6.7 Business continuity

- Point-in-time restore for SQL (7 days, extendable to 35).
- Infrastructure is fully reproducible from `infra/main.bicep`.
- If the AI provider is down, a rule-based summary is sent automatically.
- If FieldRoutes is down for one entity, the report goes out with those metrics marked unavailable.
- If everything fails, the alert fires and the report can be re-run manually: `POST /api/reports/ceo-daily?date=YYYY-MM-DD&force=true`.

## 6.8 Incident response (summary)

1. **Suspected credential exposure:** rotate the secret in Key Vault and in FieldRoutes (or Anthropic, or Teams), review `audit_log` and App Insights, and notify the President.
2. **Incorrect figure delivered:** mark the report run, post a correction to the same channel, add a regression test, and fix the definition or mapping.
3. **Unauthorized access:** disable the managed identity's role assignments or the Function App, then investigate with Entra sign-in logs.
