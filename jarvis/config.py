"""Runtime settings, read from environment variables.

In Azure, every value is an App Setting on the Function App. Secrets are never
stored as plain App Settings: they are either Key Vault references
(``@Microsoft.KeyVault(SecretUri=...)``) or fetched at runtime through
:mod:`jarvis.secrets` using the Function App's managed identity.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    env: str = "local"
    database_url: str = "sqlite:///jarvis.db"
    tenants_file: str = "config/tenants.example.yaml"
    # "fieldroutes" for live read-only API access, "sample" for the offline demo dataset.
    data_source: str = "sample"
    # Dry run writes the report to disk instead of posting to Teams. Default ON:
    # nothing is delivered anywhere until someone deliberately turns this off.
    dry_run: bool = True
    output_dir: str = "out"
    timezone: str = "America/New_York"
    report_hour_local: int = 6
    key_vault_url: str = ""
    ai_provider: str = "anthropic"  # "anthropic" | "foundry" | "none"
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"
    foundry_resource: str = ""
    teams_webhook_secret: str = "teams-ceo-report-webhook"
    ops_alert_webhook_secret: str = "teams-ops-alert-webhook"
    http_timeout_seconds: int = 60
    extra: dict = field(default_factory=dict)

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir)


def load_settings() -> Settings:
    return Settings(
        env=os.getenv("JARVIS_ENV", "local"),
        database_url=os.getenv("JARVIS_DATABASE_URL", "sqlite:///jarvis.db"),
        tenants_file=os.getenv("JARVIS_TENANTS_FILE", "config/tenants.example.yaml"),
        data_source=os.getenv("JARVIS_DATA_SOURCE", "sample"),
        dry_run=_bool("JARVIS_DRY_RUN", True),
        output_dir=os.getenv("JARVIS_OUTPUT_DIR", "out"),
        timezone=os.getenv("JARVIS_TIMEZONE", "America/New_York"),
        report_hour_local=int(os.getenv("JARVIS_REPORT_HOUR_LOCAL", "6")),
        key_vault_url=os.getenv("JARVIS_KEY_VAULT_URL", ""),
        ai_provider=os.getenv("JARVIS_AI_PROVIDER", "anthropic"),
        ai_model=os.getenv("JARVIS_AI_MODEL", "claude-opus-5-5"),
        ai_effort=os.getenv("JARVIS_AI_EFFORT", "medium"),
        foundry_resource=os.getenv("JARVIS_FOUNDRY_RESOURCE", ""),
        teams_webhook_secret=os.getenv("JARVIS_TEAMS_WEBHOOK_SECRET", "teams-ceo-report-webhook"),
        ops_alert_webhook_secret=os.getenv("JARVIS_OPS_ALERT_WEBHOOK_SECRET", "teams-ops-alert-webhook"),
        http_timeout_seconds=int(os.getenv("JARVIS_HTTP_TIMEOUT_SECONDS", "60")),
    )
