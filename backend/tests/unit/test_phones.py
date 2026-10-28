import uuid
from datetime import UTC, datetime

import pytest

from app.api import pagination
from app.services import phones


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9812345678", "+9779812345678"),  # local mobile
        ("98-1234-5678", "+9779812345678"),
        ("+977 981 234 5678", "+9779812345678"),
        ("9779812345678", "+9779812345678"),  # WhatsApp wa_id
        ("00977-9812345678", "+9779812345678"),
        ("9612345678", "+9779612345678"),  # Smart Telecom
        ("+14155552671", "+14155552671"),  # foreign, already international
        ("01-4412345", None),  # Kathmandu landline without country code: can't place reliably
        ("12345", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize(raw: str | None, expected: str | None) -> None:
    assert phones.normalize(raw) == expected


def test_extract_numbers_from_chat_text() -> None:
    text = "Mero number 9801111111 ho, or call +977-980-2222222. Order 20 chairs for 25000."
    assert phones.extract(text) == ["+9779801111111", "+9779802222222"]


def test_extract_ignores_prices_and_long_digit_runs() -> None:
    assert phones.extract("Total Rs. 9812345678901 and invoice 1234567890") == []


def test_cursor_roundtrip_and_rejects_garbage() -> None:
    stamp, row_id = datetime(2026, 10, 28, 9, 30, tzinfo=UTC), uuid.uuid4()
    assert pagination.decode(pagination.encode(stamp, row_id)) == (stamp, row_id)
    with pytest.raises(pagination.InvalidCursor):
        pagination.decode("not-a-cursor")
