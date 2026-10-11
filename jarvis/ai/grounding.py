"""Number grounding: every number the AI writes must exist in the facts.

The model is given a JSON document of pre-computed facts and told not to
calculate anything new. This module enforces that: it pulls every numeric
token out of the generated text and checks it against the set of numbers in
the facts (allowing for display rounding such as $48.2K or 85%). A narrative
containing any number that cannot be traced back to source data is rejected
and replaced; it never reaches the CEO.
"""

from __future__ import annotations

import re
from typing import Iterable

_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
_DATE_PATTERNS = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(rf"\b{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,\s*\d{{4}})?", re.I),
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),
    re.compile(r"\b(?:19|20)\d{2}\b"),          # years
    re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:AM|PM)\b", re.I),
]
_NUMBER = re.compile(r"(?<![\w.])(-?\$?-?\d[\d,]*(?:\.\d+)?)\s*([KkMm](?![a-zA-Z]))?\s*(%)?")
ALWAYS_OK = {0.0, 1.0, 2.0, 3.0}  # "top 3 actions", "1 technician" ...


def collect_numbers(obj) -> set[float]:
    out: set[float] = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= collect_numbers(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out |= collect_numbers(v)
    return out


def extract_numbers(text: str) -> list[tuple[str, float, float]]:
    """Return (token, value, tolerance) for each number in ``text``."""
    for pat in _DATE_PATTERNS:
        text = pat.sub(" ", text)
    found = []
    for m in _NUMBER.finditer(text):
        raw, suffix, _pct = m.group(1), m.group(2), m.group(3)
        digits = raw.replace("$", "").replace(",", "")
        try:
            value = float(digits)
        except ValueError:
            continue
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        mult = {"k": 1e3, "m": 1e6}.get((suffix or "").lower(), 1.0)
        tolerance = (10 ** -decimals) * mult / 2 + 1e-9
        found.append((m.group(0).strip(), value * mult, tolerance))
    return found


def ungrounded_numbers(texts: Iterable[str], facts) -> list[str]:
    allowed = collect_numbers(facts) | ALWAYS_OK
    allowed |= {abs(a) for a in allowed}
    bad = []
    for text in texts:
        for token, value, tol in extract_numbers(text):
            v = abs(value)
            if not any(abs(v - a) <= max(tol, 0.005) for a in allowed):
                bad.append(token)
    return bad
