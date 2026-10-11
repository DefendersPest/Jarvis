"""Structured logging. In Azure the Functions host forwards these records to
Application Insights; locally they go to stderr."""

from __future__ import annotations

import json
import logging
import re

_SECRET_PATTERNS = [
    re.compile(r"(authenticationKey|authenticationToken|api[_-]?key|sig|token)=([^&\s]+)", re.I),
]


class RedactingFilter(logging.Filter):
    """Defense in depth: scrub anything that looks like a credential in a URL/query."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pat in _SECRET_PATTERNS:
            msg = pat.sub(lambda m: f"{m.group(1)}=***", msg)
        record.msg, record.args = msg, ()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not any(isinstance(f, RedactingFilter) for f in root.filters):
        root.addFilter(RedactingFilter())
    for h in root.handlers:
        if not any(isinstance(f, RedactingFilter) for f in h.filters):
            h.addFilter(RedactingFilter())
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.addFilter(RedactingFilter())
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    root.setLevel(level)


def log_event(logger: logging.Logger, event: str, **fields) -> None:
    """Emit a single-line JSON event that is easy to query in Log Analytics (KQL)."""
    logger.info("jarvis_event %s", json.dumps({"event": event, **fields}, default=str))
