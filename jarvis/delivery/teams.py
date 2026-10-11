"""Microsoft Teams delivery.

Phase 1 uses a Teams **Workflows** webhook ("Post to a channel/chat when a
webhook request is received"), the Microsoft-supported replacement for the
retiring Office 365 connectors. It needs no Graph permissions: the webhook URL
itself is the credential, so it is stored in Key Vault like any other secret.

Phase 2 replaces this with an Azure Bot so executives can ask JARVIS follow-up
questions in Teams (see docs/01-architecture.md).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential, wait_random

log = logging.getLogger(__name__)

MAX_CARD_BYTES = 27_000  # Teams rejects messages much larger than ~28 KB


class DeliveryError(RuntimeError):
    pass


class _Retryable(Exception):
    pass


def wrap_card(card: dict) -> dict:
    return {
        "type": "message",
        "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None, "content": card}
        ],
    }


@retry(retry=retry_if_exception_type(_Retryable), wait=wait_exponential(multiplier=2, max=30) + wait_random(0, 2),
       stop=stop_after_attempt(4), reraise=True)
def post_card(webhook_url: str, card: dict, timeout: int = 30) -> int:
    payload = wrap_card(card)
    size = len(json.dumps(payload).encode())
    if size > MAX_CARD_BYTES:
        raise DeliveryError(f"Adaptive Card is {size} bytes; Teams limit is ~28 KB")
    try:
        resp = requests.post(webhook_url, json=payload, timeout=timeout)
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise _Retryable(str(exc)) from exc
    if resp.status_code == 429 or resp.status_code >= 500:
        raise _Retryable(f"Teams webhook HTTP {resp.status_code}")
    if resp.status_code >= 400:
        raise DeliveryError(f"Teams webhook HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.status_code


def write_dry_run(out_dir: Path, stem: str, markdown: str, html: str, card: dict) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / f"{stem}.md", out_dir / f"{stem}.html", out_dir / f"{stem}.card.json"]
    paths[0].write_text(markdown)
    paths[1].write_text(html)
    paths[2].write_text(json.dumps(wrap_card(card), indent=2))
    return paths
