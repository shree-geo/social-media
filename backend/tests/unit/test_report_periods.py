from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.services.reports import resolve_period

KTM = ZoneInfo("Asia/Kathmandu")
TODAY = date(2026, 10, 29)


def test_days_start_at_local_midnight() -> None:
    w = resolve_period("today", TODAY, KTM)
    # Kathmandu is UTC+05:45, so the local day starts at 18:15 UTC the day before.
    assert w.start.astimezone(UTC) == datetime(2026, 10, 28, 18, 15, tzinfo=UTC)
    assert w.end.astimezone(UTC) == datetime(2026, 10, 29, 18, 15, tzinfo=UTC)
    assert (w.days, w.bucket) == (1, "hour")


def test_period_lengths_and_buckets() -> None:
    assert (resolve_period("7d", TODAY, KTM).first_day, resolve_period("7d", TODAY, KTM).bucket) == (
        date(2026, 10, 23),
        "day",
    )
    assert resolve_period("30d", TODAY, KTM).days == 30
    assert resolve_period("90d", TODAY, KTM).bucket == "week"
    month = resolve_period("this_month", TODAY, KTM)
    assert (month.first_day, month.last_day) == (date(2026, 10, 1), TODAY)


def test_last_month_crosses_year() -> None:
    w = resolve_period("last_month", date(2027, 1, 15), KTM)
    assert (w.first_day, w.last_day) == (date(2026, 12, 1), date(2026, 12, 31))


def test_previous_window_is_the_same_length_just_before() -> None:
    prev = resolve_period("7d", TODAY, KTM).previous()
    assert (prev.first_day, prev.last_day, prev.days) == (date(2026, 10, 16), date(2026, 10, 22), 7)
    assert prev.end == resolve_period("7d", TODAY, KTM).start
