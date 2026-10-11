"""Secret resolution.

Production: Azure Key Vault, accessed with the Function App's managed identity
(``DefaultAzureCredential``). No secret is ever written to code, config files,
logs, or the database - the database only stores secret *names*.

Local development: if no Key Vault URL is configured, a secret named
``fieldroutes-defenders-key`` is read from the environment variable
``JARVIS_SECRET_FIELDROUTES_DEFENDERS_KEY``.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from jarvis.config import Settings

log = logging.getLogger(__name__)


class SecretNotFound(RuntimeError):
    pass


def _env_name(secret_name: str) -> str:
    return "JARVIS_SECRET_" + secret_name.upper().replace("-", "_")


@lru_cache(maxsize=4)
def _kv_client(vault_url: str):
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    return SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())


class SecretProvider:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._cache: dict[str, str] = {}

    def get(self, name: str) -> str:
        if name in self._cache:
            return self._cache[name]
        value = None
        if self._settings.key_vault_url:
            try:
                value = _kv_client(self._settings.key_vault_url).get_secret(name).value
            except Exception as exc:  # ResourceNotFoundError, auth errors, etc.
                # Log the secret *name* only, never a value.
                log.warning("Key Vault lookup failed for secret '%s': %s", name, type(exc).__name__)
        if value is None:
            value = os.getenv(_env_name(name))
        if not value:
            raise SecretNotFound(
                f"Secret '{name}' not found in Key Vault or env var {_env_name(name)}"
            )
        self._cache[name] = value
        return value

    def get_optional(self, name: str) -> str | None:
        try:
            return self.get(name)
        except SecretNotFound:
            return None
