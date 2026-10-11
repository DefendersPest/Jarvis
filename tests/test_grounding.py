from jarvis.ai.grounding import extract_numbers, ungrounded_numbers

FACTS = {"a": {"value": 48213.37}, "b": {"value": 85.37}, "c": 12, "d": [1234.0], "goal": {"target": 150000}}


def test_formatted_numbers_are_grounded():
    texts = ["Revenue reached $48,213 ($48.2K) MTD.", "Completion was 85% (85.4%).",
             "12 cancellations; 1,234 stops; goal $150K.", "Top 3 actions for Oct 12, 2026."]
    assert ungrounded_numbers(texts, FACTS) == []


def test_fabricated_numbers_are_caught():
    bad = ungrounded_numbers(["Revenue will reach $51,000 by Friday, up 7%."], FACTS)
    assert "$51,000" in bad and "7%" in bad


def test_dates_are_ignored():
    assert extract_numbers("On 2026-10-09 and Oct 9 at 6 AM") == []
