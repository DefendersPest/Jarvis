"""Source-system contract.

A connector turns a source system (FieldRoutes today; a different field
service platform at a future acquisition) into JARVIS's normalised rows. The
rest of the system never sees vendor-specific fields, which is what lets a new
company plug in without touching metrics, reports or agents.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

# Ingestion order matters only for readability of logs; entities are independent.
ENTITIES = ("employees", "customers", "subscriptions", "appointments", "invoices", "payments")


class EntityUnsupported(Exception):
    """The source cannot provide this entity (no API permission, no such module).
    Metrics depending on it are reported as UNAVAILABLE - never as zero."""


class SourceError(Exception):
    """A transient or permanent failure talking to the source system."""


class DataSource(Protocol):
    name: str

    def fetch(self, entity: str, start: date, end: date) -> list[dict]:
        """Return normalised rows for ``entity`` relevant to [start, end].

        Each row has ``source_id`` plus the column names of the matching
        model in :mod:`jarvis.db.models`, and ``branch_source_id`` (the
        source office id) which ingestion resolves to ``branch_id``.
        """
        ...
