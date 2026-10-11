# 2. Required Software, Azure Services and Monthly Costs

## 2.1 Azure services (deployed by `infra/main.bicep`)

| Service | SKU / configuration | Purpose |
|---|---|---|
| Resource group | `rg-jarvis-prod` (East US 2 suggested) | Container for everything |
| Azure Functions | Flex Consumption (FC1), Python 3.11, system-assigned managed identity | Scheduled and on-demand jobs |
| Storage account | Standard LRS, shared-key access disabled | Functions runtime state and deployment package |
| Azure SQL Database | General Purpose serverless Gen5, 0.5-2 vCores, auto-pause 60 min, **free offer enabled**, Entra-only auth | Central multi-company database |
| Key Vault | Standard, RBAC, soft delete + purge protection | All credentials |
| Application Insights + Log Analytics | Workspace-based, 30-day retention, 1 GB/day cap | Logs, traces, alerts |
| Azure Monitor alerts + action group | 2 log alerts (run failed, run missing) | Failure notification |
| Cost Management budget | default $150/month, alerts at 80% actual and 100% forecast | Cost guardrail |
| *Phase 2:* Azure Bot Service | F0 / standard channels (free) | Two-way Teams conversations |

## 2.2 Other software and accounts

| Item | Needed for | Notes |
|---|---|---|
| FieldRoutes API access, per company | Data | Confirm with your FieldRoutes account manager whether API access carries a fee and what the rate limits are |
| Microsoft Teams + Workflows (Power Automate) | Delivery | Included with Microsoft 365 business plans. The webhook trigger and Teams actions are standard connectors. |
| Anthropic API account **or** Claude in Microsoft Foundry | AI narrative | Pay-as-you-go. Set a monthly spend limit in the Anthropic Console. |
| Power BI Pro (existing) | Dashboards on the JARVIS database | No new cost if already licensed |
| GitHub (this repository) | Source control, CI | Free tier is sufficient |
| Developer tools | Python 3.11, Azure CLI, Azure Functions Core Tools v4 | Free |

## 2.3 Estimated monthly operating cost

These are estimates at list prices (US regions, October 2026) for current usage: 2 companies, 1 daily report, about 22 runs a month. Confirm them with the [Azure pricing calculator](https://azure.microsoft.com/pricing/calculator/) before approval.

| Item | Phase 1 (2 companies) | Growth (5-6 companies, 5+ agents, Teams bot) | Basis |
|---|---:|---:|---|
| Azure Functions (Flex Consumption) | $0-2 | $5-20 | Free grant covers 100k GB-seconds and 250k executions a month. A daily run uses about 1-2 minutes at 2 GB. |
| Azure SQL serverless | $0-15 | $25-80 | Free offer: 100k vCore-seconds and 32 GB a month. Each wake-up bills at least 0.5 vCore until auto-pause. Daily sync plus Power BI refreshes stay near the free limit; overage is billed rather than pausing. |
| Storage | $1-3 | $2-5 | |
| Key Vault | <$1 | <$1 | $0.03 per 10k operations |
| Application Insights / Log Analytics | $0-5 | $5-25 | First 5 GB a month free; 1 GB/day cap |
| Claude API (`claude-opus-5-5`, $4 / $20 per million tokens in/out) | $3-8 | $20-60 | About 10-15k input and 2-4k output tokens a run, roughly $0.10-0.20 per report. Agents and the bot add more. |
| Azure Bot | - | $0 | Standard channels are free |
| **Total (excluding FieldRoutes API fees and existing M365/Power BI licenses)** | **~$10-35 / month** | **~$60-190 / month** | |

**Cost controls built in:**

- Consumption-based compute.
- SQL auto-pause and free offer.
- Log ingestion cap.
- Azure budget alert at $150.
- An Anthropic workspace spend limit (recommended).
- AI effort set to `medium`. Change it with `JARVIS_AI_EFFORT`.
- The AI is called once per report, on summarized facts, never on raw records.

**What would change the estimate:**

- Running Power BI refreshes every hour (keeps SQL awake: about +$20-40).
- Private networking in Phase 3 (private endpoints about $7-8 each a month, plus VNet integration).
- Much larger companies (more rows; still small for Azure SQL).
