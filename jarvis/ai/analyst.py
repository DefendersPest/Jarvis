"""AI business analyst for the CEO report.

The model receives the computed facts (JSON) and returns a structured
narrative: headline, executive summary, exactly three management actions,
watch items and data caveats. It is told to use only numbers present in the
facts; :mod:`jarvis.ai.grounding` then verifies that. If the AI is not
configured, refuses, errors or fails validation twice, a deterministic
rule-based narrative is used instead and the report says so.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from jarvis.ai.grounding import ungrounded_numbers
from jarvis.config import Settings
from jarvis.delivery.fmt import pct, usd
from jarvis.logging_setup import log_event
from jarvis.secrets import SecretProvider

log = logging.getLogger(__name__)


class Action(BaseModel):
    title: str
    why: str
    owner: str
    metric_keys: list[str]


class Narrative(BaseModel):
    headline: str
    executive_summary: str
    top_actions: list[Action]
    watch_items: list[str]
    data_caveats: list[str]


NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One line, under 15 words."},
        "executive_summary": {"type": "string", "description": "3-5 sentences, under 110 words."},
        "top_actions": {
            "type": "array",
            "description": "Exactly three actions, most important first.",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "why": {"type": "string"},
                    "owner": {"type": "string", "description": "Role responsible, e.g. 'Operations Manager'."},
                    "metric_keys": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "why", "owner", "metric_keys"],
                "additionalProperties": False,
            },
        },
        "watch_items": {"type": "array", "items": {"type": "string"}},
        "data_caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "executive_summary", "top_actions", "watch_items", "data_caveats"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are JARVIS, the business analyst for the President of The Defenders, a pest control \
and lawn care company in Northeast Florida that is acquiring and operating several pest control companies \
(for example BugPro). Every weekday morning you turn yesterday's computed business metrics into a short \
briefing the President can read in under two minutes.

How to work with the data:
- The user message contains a JSON document of facts computed directly from FieldRoutes. It is the only \
source of truth. Use only numbers that appear in it, formatted as you like ($48.2K, 85%). Do not add, \
subtract, average, or project numbers yourself; the facts already include goal gaps and pacing. If you \
want a number that isn't there, describe the situation in words instead.
- Metrics with status "unavailable" have no value. Say they are unavailable and why; never estimate them, \
and never treat them as zero. "partial" totals exclude the companies named in their reason - say so when \
you cite them.
- If the facts are labelled sample data, write normally; the report header already flags it.

What to write:
- headline: the single most important takeaway.
- executive_summary: revenue and pace against goal first, then operations, sales and retention. Plain \
business language, no jargon, no filler.
- top_actions: exactly three, ranked by business impact. Each names a concrete action someone can take \
today, the owner role, why it matters (citing the facts), and the metric keys it relates to (keys from the \
facts, such as "revenue_billed_mtd"). Prefer actions tied to findings with high severity.
- watch_items: up to three things that aren't urgent yet but are trending the wrong way.
- data_caveats: every unavailable or partial metric that affects the picture, in one short line each.
"""


@dataclass
class AnalystResult:
    narrative: Narrative
    ai_used: bool
    model: str | None
    note: str | None = None


class Analyst:
    def __init__(self, settings: Settings, secrets: SecretProvider):
        self.settings = settings
        self.secrets = secrets

    # ------------------------------------------------------------------ public
    def write(self, facts: dict) -> AnalystResult:
        if self.settings.ai_provider == "none":
            return AnalystResult(deterministic_narrative(facts), False, None, "AI disabled by configuration")
        try:
            client = self._client()
        except Exception as exc:
            return AnalystResult(deterministic_narrative(facts), False, None, f"AI not configured ({exc})")

        feedback: tuple[str, str] | None = None  # (previous draft, what was wrong)
        for attempt in (1, 2):
            try:
                narrative = self._generate(client, facts, feedback)
            except _Refused as exc:
                return AnalystResult(deterministic_narrative(facts), False, self.settings.ai_model, str(exc))
            except Exception as exc:  # API errors after SDK retries, malformed output
                log.warning("AI generation attempt %s failed: %s", attempt, exc)
                feedback = ("(unusable response)", f"Your previous response could not be used: {exc}. Return valid JSON matching the schema.")
                continue
            problems = validate(narrative, facts)
            if not problems:
                log_event(log, "ai.narrative.ok", attempt=attempt, model=self.settings.ai_model)
                return AnalystResult(narrative, True, self.settings.ai_model)
            log.warning("AI narrative failed validation (attempt %s): %s", attempt, problems)
            feedback = (
                narrative.model_dump_json(),
                "Your previous response was rejected: " + "; ".join(problems)
                + ". Rewrite it using only numbers that appear in the facts.",
            )
        return AnalystResult(
            deterministic_narrative(facts), False, self.settings.ai_model,
            "AI narrative failed validation twice; rule-based summary used",
        )

    # ------------------------------------------------------------------ internals
    def _client(self):
        import anthropic

        if self.settings.ai_provider == "foundry":
            return anthropic.AnthropicFoundry(
                api_key=self.secrets.get("foundry-api-key"), resource=self.settings.foundry_resource
            )
        key = self.secrets.get_optional("anthropic-api-key")
        return anthropic.Anthropic(api_key=key, max_retries=4) if key else anthropic.Anthropic(max_retries=4)

    def _generate(self, client, facts: dict, feedback: tuple[str, str] | None) -> Narrative:
        content = "Facts for today's briefing:\n```json\n" + json.dumps(facts, default=str) + "\n```"
        messages = [{"role": "user", "content": content}]
        if feedback:
            messages.append({"role": "assistant", "content": feedback[0]})
            messages.append({"role": "user", "content": feedback[1]})
        kwargs = dict(
            model=self.settings.ai_model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=messages,
            output_config={
                "effort": self.settings.ai_effort,
                "format": {"type": "json_schema", "schema": NARRATIVE_SCHEMA},
            },
        )
        if self.settings.ai_provider == "anthropic":
            # Server-side fallback: if the model declines, the API retries on Anthropic's recommended model.
            response = client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        else:
            response = client.messages.create(**kwargs)
        log_event(log, "ai.usage", model=response.model, request_id=getattr(response, "_request_id", None),
                  input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens)
        if response.stop_reason == "refusal":
            raise _Refused("AI declined the request; rule-based summary used")
        if response.stop_reason == "max_tokens":
            raise ValueError("response truncated")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            raise ValueError("no text block in response")
        try:
            return Narrative.model_validate_json(text)
        except ValidationError as exc:
            raise ValueError(f"schema validation failed: {exc.errors()[:2]}") from exc


class _Refused(Exception):
    pass


def known_metric_keys(facts: dict) -> set[str]:
    keys = set(facts.get("portfolio", {}).get("metrics", {}).keys())
    for c in facts.get("companies", []):
        keys |= set(c.get("metrics", {}).keys())
    return keys


def validate(n: Narrative, facts: dict) -> list[str]:
    problems = []
    if len(n.top_actions) != 3:
        problems.append(f"expected exactly 3 top_actions, got {len(n.top_actions)}")
    keys = known_metric_keys(facts)
    for a in n.top_actions:
        unknown = [k for k in a.metric_keys if k not in keys]
        if unknown:
            problems.append(f"unknown metric_keys {unknown}")
    texts = [n.headline, n.executive_summary, *n.watch_items, *n.data_caveats]
    for a in n.top_actions:
        texts += [a.title, a.why, a.owner]
    bad = ungrounded_numbers(texts, facts)
    if bad:
        problems.append(f"numbers not found in facts: {sorted(set(bad))[:10]}")
    return problems


# --------------------------------------------------------------------------- rule-based fallback
_ACTION_TEMPLATES = {
    "revenue": ("Close the revenue gap to goal", "General Manager"),
    "sales": ("Push sales activity to get back on pace", "Sales Manager"),
    "operations": ("Recover missed stops and fix the routing cause", "Operations Manager"),
    "billing": ("Audit completed services that were not billed", "Office Manager"),
    "retention": ("Run save calls on recent cancellations", "Customer Service Manager"),
    "data": ("Restore the missing data feed", "JARVIS Administrator"),
}


def deterministic_narrative(facts: dict) -> Narrative:
    """Rule-based narrative built only from the facts - used whenever the AI
    path is unavailable, so the report always goes out on time."""
    p = facts.get("portfolio", {}).get("metrics", {})

    def v(key):
        m = p.get(key)
        return m["value"] if m and m["status"] != "unavailable" else None

    bits = []
    rev_mtd, rev_day = v("revenue_billed_mtd"), v("revenue_billed_day")
    if rev_mtd is not None:
        bits.append(f"Billed revenue was {usd(rev_day)} for the period and {usd(rev_mtd)} month-to-date.")
    else:
        bits.append("Billed revenue is unavailable today.")
    goal_lines = []
    for c in facts.get("companies", []):
        g = (c["metrics"].get("revenue_billed_mtd") or {}).get("goal")
        if g:
            goal_lines.append(f"{c['company_name']} is at {pct(g['attainment_pct'])} of revenue goal pace")
    if goal_lines:
        bits.append("; ".join(goal_lines) + ".")
    comp, missed = v("appointments_completed_day"), v("appointments_missed_day")
    if comp is not None:
        bits.append(f"Technicians completed {comp:,.0f} appointments; {missed:,.0f} were missed.")
    sold, canc = v("new_subscriptions_day"), v("cancellations_day")
    if sold is not None:
        bits.append(f"Sales added {sold:,.0f} subscriptions against {canc:,.0f} cancellations.")

    findings = []
    for c in facts.get("companies", []):
        for f in c.get("findings", []):
            findings.append((c["company_name"], f))
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    findings.sort(key=lambda x: order.get(x[1]["severity"], 9))

    actions: list[Action] = []
    seen = set()
    for company, f in findings:
        key = (company, f["category"])
        if key in seen:
            continue
        seen.add(key)
        title, owner = _ACTION_TEMPLATES.get(f["category"], ("Review this issue", "General Manager"))
        mk = f["detail"].get("metric")
        actions.append(Action(title=f"{company}: {title}", why=f["title"], owner=owner,
                              metric_keys=[mk] if mk else []))
        if len(actions) == 3:
            break
    while len(actions) < 3:
        actions.append(Action(title="No further priority issues detected", why="All tracked rules passed.",
                              owner="General Manager", metric_keys=[]))

    # Unavailable metrics are listed by the renderer straight from the facts, so no caveats are duplicated here.
    caveats: list[str] = []
    headline = actions[0].why if findings else "No priority issues detected"
    return Narrative(headline=headline, executive_summary=" ".join(bits), top_actions=actions,
                     watch_items=[], data_caveats=caveats)
