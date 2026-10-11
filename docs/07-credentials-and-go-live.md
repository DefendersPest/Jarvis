# 7. Credentials Request and Go-Live Checklist

**Please do not send any password, API key, token or webhook URL by chat, e-mail or text, including to me.** After the infrastructure is approved and deployed, an authorized admin enters each secret directly into Azure Key Vault. JARVIS reads secrets at run time with its managed identity; no person or file ever needs to see them again.

## 7.1 What I need, and from whom

| # | Item | Who provides it | Where it goes |
|---|---|---|---|
| 1 | Approval to create the Azure resource group and the $150/month budget (gate G1) | President | - |
| 2 | Azure subscription ID, and the Entra group "JARVIS SQL Admins" (2 people) with its object ID | IT / Microsoft 365 admin | `infra/main.parameters.json` (not secret) |
| 3 | Alert e-mail address | President / IT | parameters file (not secret) |
| 4 | FieldRoutes API key + token, **The Defenders** | FieldRoutes admin / account manager | Key Vault: `fieldroutes-defenders-auth-key`, `fieldroutes-defenders-auth-token` |
| 5 | FieldRoutes subdomain and office IDs, **The Defenders** | FieldRoutes admin | `config/tenants.yaml` (not secret) |
| 6 | FieldRoutes API reference documentation, rate limits, any API fee | FieldRoutes account manager | Shared with the engineering team |
| 7 | Same as 4-5 for **BugPro** (Phase 2) | BugPro FieldRoutes admin | `fieldroutes-bugpro-auth-key`, `fieldroutes-bugpro-auth-token` |
| 8 | Anthropic API key (workspace "JARVIS", spend limit set), **or** a Foundry deployment | President / finance | Key Vault: `anthropic-api-key` (or `foundry-api-key`) |
| 9 | Teams Workflows webhook URL: test channel first, CEO channel or chat at go-live | Owner of the channel | Key Vault: `teams-ceo-report-webhook` |
| 10 | Teams Workflows webhook URL for IT alerts | IT | Key Vault: `teams-ops-alert-webhook` |
| 11 | Confirmed metric definitions and real monthly goals | President / CFO / Ops | `config/tenants.yaml` (not secret) |

## 7.2 How an admin stores a secret

In the Azure portal, open **Key Vault → Secrets → Generate/Import**. Or use Azure CLI while signed in with MFA:

```bash
# Prompts for the value so it never lands in shell history
read -rs VALUE && az keyvault secret set --vault-name <kv-name> \
  --name fieldroutes-defenders-auth-key --value "$VALUE" --output none && unset VALUE
```

## 7.3 Go-live checklist

- [ ] G1 approved; `infra/main.bicep` deployed; `infra/post-deploy.sql` run.
- [ ] Schema created by a SQL admin (Entra sign-in via `az login`): `JARVIS_DATABASE_URL=<prod url> python -m jarvis.cli init-db`, then the tenants loaded with `python -m jarvis.cli tenants sync --file config/tenants.yaml`.
- [ ] Code deployed to the Function App (`func azure functionapp publish <name>` or the CI deploy job).
- [ ] Secrets 4, 5, 8, 9 (test channel) and 10 stored in Key Vault.
- [ ] `python scripts/verify_fieldroutes.py --company defenders` passes. Every `VERIFY` item in `jarvis/connectors/fieldroutes_mapping.py` confirmed or corrected; tests green.
- [ ] Metric definitions signed off (`docs/metric-definitions.md`); real goals loaded.
- [ ] History backfilled (60-90 days).
- [ ] G2 approved. App settings changed to `JARVIS_DATA_SOURCE=fieldroutes` and `JARVIS_DRY_RUN=false`, delivering to the **test** channel.
- [ ] 10 business days of parallel run, reconciled against FieldRoutes reports with no unexplained differences.
- [ ] Failure alert tested (temporarily remove a secret, confirm the alert, restore it).
- [ ] G3 approved. Webhook secret replaced with the CEO channel or chat URL.
