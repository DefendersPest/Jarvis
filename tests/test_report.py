import dataclasses
import json
from datetime import date
from types import SimpleNamespace

from sqlalchemy import select

from jarvis.ai import analyst as analyst_mod
from jarvis.db.models import ReportRun
from jarvis.db.session import session_scope
from jarvis.delivery import teams
from jarvis.reports.ceo_daily import run_ceo_report


def test_end_to_end_dry_run(settings):
    r = run_ceo_report(settings, run_date=date(2026, 10, 13))
    assert r.status == "generated" and len(r.outputs) == 3
    md = open(r.outputs[0]).read()
    assert "SAMPLE DATA - NOT REAL" in md
    assert "UNAVAILABLE" in md  # BugPro payments are configured as unsupported
    card = json.loads(open(r.outputs[2]).read())
    assert card["attachments"][0]["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert len(json.dumps(card)) < teams.MAX_CARD_BYTES


def test_delivered_report_is_not_resent(settings, monkeypatch):
    sent = []
    monkeypatch.setattr(teams, "post_card", lambda url, card: sent.append(card) or 202)
    monkeypatch.setenv("JARVIS_SECRET_TEAMS_CEO_REPORT_WEBHOOK", "https://example.invalid/hook")
    live = dataclasses.replace(settings, dry_run=False)
    first = run_ceo_report(live, run_date=date(2026, 10, 13))
    second = run_ceo_report(live, run_date=date(2026, 10, 13))
    assert first.status == "delivered" and second.skipped and len(sent) == 1
    run_ceo_report(live, run_date=date(2026, 10, 13), force=True)
    assert len(sent) == 2


def test_failure_is_recorded(settings, monkeypatch):
    live = dataclasses.replace(settings, dry_run=False)  # no webhook secret configured
    try:
        run_ceo_report(live, run_date=date(2026, 10, 13))
    except Exception:
        pass
    else:
        raise AssertionError("expected failure")
    with session_scope(settings.database_url) as s:
        run = s.scalar(select(ReportRun))
        assert run.status == "failed" and "SecretNotFound" in run.error


# ----------------------------------------------------------------------------- AI path (fake client)
def _fake_client(texts):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        text = texts[min(len(calls) - 1, len(texts) - 1)]
        return SimpleNamespace(stop_reason="end_turn", model=kwargs["model"],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                               content=[SimpleNamespace(type="text", text=text)])

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    return client, calls


def _narrative(summary, keys=("revenue_billed_mtd",)):
    act = {"title": "Recover missed stops", "why": "Operations missed stops.", "owner": "Operations Manager",
           "metric_keys": list(keys)}
    return json.dumps({"headline": "Steady day", "executive_summary": summary, "top_actions": [act, act, act],
                       "watch_items": [], "data_caveats": []})


def test_ai_narrative_used_when_grounded(with_ai, monkeypatch):
    client, calls = _fake_client([_narrative("Revenue was solid and operations held up.")])
    monkeypatch.setattr(analyst_mod.Analyst, "_client", lambda self: client)
    r = run_ceo_report(with_ai, run_date=date(2026, 10, 13))
    assert r.narrative_source.startswith("AI (")
    assert calls[0]["fallbacks"] == "default" and calls[0]["output_config"]["format"]["type"] == "json_schema"


def test_fabricated_number_is_rejected(with_ai, monkeypatch):
    client, calls = _fake_client([_narrative("Revenue will hit $987,654 this month.")])
    monkeypatch.setattr(analyst_mod.Analyst, "_client", lambda self: client)
    r = run_ceo_report(with_ai, run_date=date(2026, 10, 13))
    assert len(calls) == 2  # one retry with feedback
    assert "987,654" in calls[1]["messages"][-1]["content"]
    assert r.narrative_source.startswith("rule-based")
    assert "987,654" not in open(r.outputs[0]).read()


def test_unknown_metric_key_is_rejected(with_ai, monkeypatch):
    client, _ = _fake_client([_narrative("Fine.", keys=("made_up_metric",))])
    monkeypatch.setattr(analyst_mod.Analyst, "_client", lambda self: client)
    r = run_ceo_report(with_ai, run_date=date(2026, 10, 13))
    assert r.narrative_source.startswith("rule-based")


def test_rule_based_narrative_passes_its_own_grounding_check(settings):
    run_ceo_report(settings, run_date=date(2026, 10, 13))
    with session_scope(settings.database_url) as s:
        facts = s.scalar(select(ReportRun)).facts
    assert analyst_mod.validate(analyst_mod.deterministic_narrative(facts), facts) == []
