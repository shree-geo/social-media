from decimal import Decimal

import pytest

from app.services.amount_words import integer_words, rupees_in_words


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (0, "Zero"),
        (15, "Fifteen"),
        (105, "One Hundred Five"),
        (4500, "Four Thousand Five Hundred"),
        (101700, "One Lakh One Thousand Seven Hundred"),
        (1250000, "Twelve Lakh Fifty Thousand"),
        (23456789, "Two Crore Thirty Four Lakh Fifty Six Thousand Seven Hundred Eighty Nine"),
    ],
)
def test_integer_words_use_lakh_and_crore(n: int, words: str) -> None:
    assert integer_words(n) == words


def test_rupees_with_and_without_paisa() -> None:
    assert (
        rupees_in_words(Decimal("117570.50"))
        == "Rupees One Lakh Seventeen Thousand Five Hundred Seventy and Fifty Paisa Only"
    )
    assert rupees_in_words(Decimal("6000")) == "Rupees Six Thousand Only"
