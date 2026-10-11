"""Number formatting shared by the renderer and the deterministic narrative."""

from __future__ import annotations


def usd(x: float | None, cents: bool = False) -> str:
    if x is None:
        return "n/a"
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}" if cents else f"{sign}${abs(x):,.0f}"


def num(x: float | None) -> str:
    return "n/a" if x is None else f"{x:,.0f}"


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1f}%"


def metric_value(m: dict) -> str:
    if m["status"] == "unavailable":
        return "UNAVAILABLE"
    v, unit = m["value"], m["unit"]
    text = usd(v) if unit == "usd" else usd(v, cents=True) if unit == "usd_avg" else pct(v) if unit == "pct" else num(v)
    return text + (" (partial)" if m["status"] == "partial" else "")
