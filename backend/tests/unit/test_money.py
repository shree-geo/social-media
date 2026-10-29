from decimal import Decimal as D

import pytest

from app.services.money import InvalidLine, LineInput, balance, line_amounts, money, totals


def test_tax_exclusive_line() -> None:
    a = line_amounts(LineInput(D("20"), D("4500"), D("0"), D("13")), prices_include_tax=False)
    assert (a.net, a.tax_amount, a.line_total) == (D("90000.00"), D("11700.00"), D("101700.00"))


def test_tax_inclusive_line_splits_vat_out() -> None:
    # Shelf price 1130 including 13% VAT → 1000 + 130.
    a = line_amounts(LineInput(D("1"), D("1130"), D("0"), D("13")), prices_include_tax=True)
    assert (a.net, a.tax_amount, a.line_total) == (D("1000.00"), D("130.00"), D("1130.00"))


def test_inclusive_rounding_always_adds_up() -> None:
    a = line_amounts(LineInput(D("3"), D("99.99"), D("0"), D("13")), prices_include_tax=True)
    assert a.net + a.tax_amount == a.line_total == D("299.97")


def test_discount_and_fractional_quantity() -> None:
    a = line_amounts(LineInput(D("2.5"), D("400"), D("100"), D("0")), prices_include_tax=False)
    assert (a.net, a.tax_amount, a.line_total) == (D("900.00"), D("0.00"), D("900.00"))


@pytest.mark.parametrize(
    "line",
    [
        LineInput(D("0"), D("10"), D("0"), D("13")),
        LineInput(D("1"), D("10"), D("11"), D("13")),
        LineInput(D("1"), D("10"), D("-1"), D("13")),
    ],
)
def test_invalid_lines(line: LineInput) -> None:
    with pytest.raises(InvalidLine):
        line_amounts(line, prices_include_tax=False)


def test_order_totals_with_shipping() -> None:
    lines = [
        LineInput(D("20"), D("4500"), D("1000"), D("13")),
        LineInput(D("5"), D("6000"), D("0"), D("13")),
    ]
    computed = [(line, line_amounts(line, prices_include_tax=False)) for line in lines]
    t = totals(computed, shipping_fee=D("500"))
    assert t.subtotal == D("119000.00")
    assert t.discount_total == D("1000.00")
    assert t.tax_total == D("15470.00")
    assert t.grand_total == D("119000.00") + D("15470.00") + D("500.00")


def test_money_rounds_half_up() -> None:
    assert money("2.345") == D("2.35") and money("2.344") == D("2.34")


@pytest.mark.parametrize(
    ("paid", "refunded", "expected"),
    [
        ("0", "0", ("0.00", "1000.00", "UNPAID")),
        ("400", "0", ("400.00", "600.00", "PARTIAL")),
        ("1000", "0", ("1000.00", "0.00", "PAID")),
        ("1000", "300", ("700.00", "300.00", "PARTIAL")),
        ("1000", "1000", ("0.00", "1000.00", "REFUNDED")),
    ],
)
def test_balance_rule(paid: str, refunded: str, expected: tuple[str, str, str]) -> None:
    b = balance(D("1000"), paid=D(paid), refunded=D(refunded))
    assert (str(b.amount_paid), str(b.amount_due), b.payment_status) == expected
