"""Agent framework - the extension point for future JARVIS capabilities.

Every agent (retention, cross-sell, technician performance, finance,
acquisition integration, onboarding, marketing, executive scheduling) follows
the same contract:

* reads from the central database (never directly from source systems),
* writes its results as ``AgentFinding`` rows and/or a report,
* declares the permissions it needs in the ``agents`` table; anything outside
  that list is refused by :func:`require`,
* any action that touches the outside world (posting to Teams, e-mailing,
  scheduling) goes through an approval gate and is written to ``audit_log``.

The Daily CEO Report is the first agent; see jarvis/reports/ceo_daily.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from jarvis.db.models import AgentDefinition

# Actions an agent may be granted. Customer-facing and write-back actions are
# deliberately absent; adding one requires a design review and an approval workflow.
KNOWN_PERMISSIONS = {
    "read:metrics",
    "read:operational",
    "write:findings",
    "post:teams",
    "read:calendar",
    "draft:email",        # drafts only - a human sends
}


class PermissionDenied(RuntimeError):
    pass


@dataclass
class AgentContext:
    session: Session
    run_date: date
    company_ids: list[int]
    config: dict = field(default_factory=dict)


class Agent(ABC):
    key: str
    name: str
    required_permissions: set[str] = set()

    @abstractmethod
    def run(self, ctx: AgentContext) -> dict:
        """Do the work; return a summary dict for logging."""


def require(session: Session, agent_key: str, permission: str) -> None:
    agent = session.scalar(select(AgentDefinition).where(AgentDefinition.key == agent_key))
    if agent is None or not agent.enabled:
        raise PermissionDenied(f"Agent '{agent_key}' is not registered or not enabled")
    if permission not in KNOWN_PERMISSIONS or permission not in (agent.permissions or []):
        raise PermissionDenied(f"Agent '{agent_key}' lacks permission '{permission}'")


REGISTRY: dict[str, type[Agent]] = {}


def register(cls: type[Agent]) -> type[Agent]:
    REGISTRY[cls.key] = cls
    return cls
