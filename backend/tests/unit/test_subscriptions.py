from datetime import date

import pytest

from app.services.numbering import nepali_fiscal_year_key, period_key
from app.services.subscriptions import Access, access_for, effective_status, period_end

EXPIRY = date(2026, 12, 31)


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 12, 31), "ACTIVE"),  # last covered day
        (date(2027, 1, 1), "GRACE"),
        (date(2027, 1, 7), "GRACE"),  # 7-day grace inclusive
        (date(2027, 1, 8), "EXPIRED"),
    ],
)
def test_active_moves_through_grace_to_expired(today: date, expected: str) -> None:
    assert (
        effective_status("ACTIVE", trial_ends_at=None, expiry_date=EXPIRY, grace_period_days=7, today=today) == expected
    )


def test_trial_expires_without_grace() -> None:
    kwargs = {"trial_ends_at": date(2026, 11, 13), "expiry_date": date(2026, 11, 13), "grace_period_days": 7}
    assert effective_status("TRIAL", today=date(2026, 11, 13), **kwargs) == "TRIAL"  # type: ignore[arg-type]
    assert effective_status("TRIAL", today=date(2026, 11, 14), **kwargs) == "EXPIRED"  # type: ignore[arg-type]


@pytest.mark.parametrize("status", ["SUSPENDED", "CANCELLED", "EXPIRED"])
def test_manual_and_terminal_states_are_not_changed_by_dates(status: str) -> None:
    assert (
        effective_status(status, trial_ends_at=None, expiry_date=EXPIRY, grace_period_days=7, today=date(2026, 1, 1))
        == status
    )


@pytest.mark.parametrize(
    ("status", "access"),
    [
        ("TRIAL", Access.FULL),
        ("ACTIVE", Access.FULL),
        ("GRACE", Access.FULL),
        ("EXPIRED", Access.READ_ONLY),
        ("SUSPENDED", Access.BLOCKED),
        ("CANCELLED", Access.BLOCKED),
        (None, Access.BLOCKED),
    ],
)
def test_access_levels(status: str | None, access: Access) -> None:
    assert access_for(status) is access


@pytest.mark.parametrize(
    ("start", "cycle", "end"),
    [
        (date(2026, 10, 28), "yearly", date(2027, 10, 27)),
        (date(2026, 10, 28), "monthly", date(2026, 11, 27)),
        (date(2026, 1, 31), "monthly", date(2026, 2, 27)),  # month-end clamps, then minus one day
        (date(2026, 1, 1), "quarterly", date(2026, 3, 31)),
        (date(2026, 1, 1), "half_yearly", date(2026, 6, 30)),
    ],
)
def test_period_end(start: date, cycle: str, end: date) -> None:
    assert period_end(start, cycle) == end


@pytest.mark.parametrize(
    ("today", "key"),
    [
        (date(2026, 10, 28), "2083-84"),  # after 1 Shrawan 2083
        (date(2026, 7, 1), "2082-83"),  # before the new fiscal year
        (date(2026, 1, 15), "2082-83"),
    ],
)
def test_nepali_fiscal_year_key(today: date, key: str) -> None:
    assert nepali_fiscal_year_key(today) == key


def test_period_key_by_tenant_setting() -> None:
    assert period_key("ad_year", date(2026, 10, 28)) == "2026"
    assert period_key("np_fiscal_year", date(2026, 10, 28)) == "2083-84"
