"""Date windows and schedule gating.

Azure Functions on Linux evaluates timer CRON expressions in UTC and does not
support WEBSITE_TIME_ZONE. Eastern time shifts between UTC-5 and UTC-4, so the
timer fires at both 10:00 and 11:00 UTC on weekdays and :func:`is_report_hour`
lets only the run that lands on 6 AM Eastern proceed. DST is handled by
``zoneinfo``, with no manual adjustment twice a year.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ReportWindow:
    run_date: date          # local date the report is produced
    day_start: date         # first day of the "daily" period (inclusive)
    day_end: date           # last day of the "daily" period (inclusive)
    mtd_start: date         # first day of the month containing day_end
    mtd_end: date           # == day_end

    @property
    def label(self) -> str:
        if self.day_start == self.day_end:
            return self.day_end.strftime("%a %b %-d, %Y")
        return f"{self.day_start:%a %b %-d} - {self.day_end:%a %b %-d, %Y}"

    @property
    def is_multi_day(self) -> bool:
        return self.day_start != self.day_end


def local_now(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))


def is_report_hour(now_utc: datetime, tz: str, hour: int) -> bool:
    """True when ``now_utc`` falls in the configured local hour on a weekday."""
    local = now_utc.astimezone(ZoneInfo(tz))
    return local.weekday() < 5 and local.hour == hour


def report_window(run_date: date) -> ReportWindow:
    """The period a report produced on ``run_date`` covers.

    Reports run Monday-Friday. Each one covers everything since the previous
    report: Tue-Fri cover yesterday; Monday covers Friday through Sunday, so
    weekend activity (online sign-ups, Saturday routes, cancellations) is never
    skipped. Month-to-date always runs through the end of the daily period.
    """
    day_end = run_date - timedelta(days=1)
    day_start = run_date - timedelta(days=3) if run_date.weekday() == 0 else day_end
    return ReportWindow(
        run_date=run_date,
        day_start=day_start,
        day_end=day_end,
        mtd_start=day_end.replace(day=1),
        mtd_end=day_end,
    )


def workdays_between(start: date, end: date, workdays: set[int]) -> int:
    """Count days in [start, end] whose weekday() is in ``workdays`` (0=Mon)."""
    if end < start:
        return 0
    n = 0
    d = start
    while d <= end:
        if d.weekday() in workdays:
            n += 1
        d += timedelta(days=1)
    return n


def month_bounds(d: date) -> tuple[date, date]:
    last = calendar.monthrange(d.year, d.month)[1]
    return d.replace(day=1), d.replace(day=last)
