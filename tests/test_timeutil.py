from datetime import date, datetime, timezone

from jarvis.timeutil import is_report_hour, report_window, workdays_between


def test_tuesday_covers_yesterday():
    w = report_window(date(2026, 10, 13))
    assert (w.day_start, w.day_end) == (date(2026, 10, 12), date(2026, 10, 12))
    assert w.mtd_start == date(2026, 10, 1)


def test_monday_covers_weekend():
    w = report_window(date(2026, 10, 12))
    assert (w.day_start, w.day_end) == (date(2026, 10, 9), date(2026, 10, 11))
    assert w.is_multi_day


def test_month_boundary_mtd_follows_day_end():
    w = report_window(date(2026, 11, 2))  # Monday
    assert w.day_start == date(2026, 10, 30)
    assert w.mtd_start == date(2026, 11, 1) and w.mtd_end == date(2026, 11, 1)


def test_report_hour_handles_dst():
    tz = "America/New_York"
    # Summer (EDT, UTC-4): 10:00 UTC is 6 AM local
    assert is_report_hour(datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc), tz, 6)
    assert not is_report_hour(datetime(2026, 7, 14, 11, 0, tzinfo=timezone.utc), tz, 6)
    # Winter (EST, UTC-5): 11:00 UTC is 6 AM local
    assert is_report_hour(datetime(2026, 1, 13, 11, 0, tzinfo=timezone.utc), tz, 6)
    assert not is_report_hour(datetime(2026, 1, 13, 10, 0, tzinfo=timezone.utc), tz, 6)
    # Never on Saturday
    assert not is_report_hour(datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc), tz, 6)


def test_workdays_between():
    assert workdays_between(date(2026, 10, 5), date(2026, 10, 11), {0, 1, 2, 3, 4}) == 5
