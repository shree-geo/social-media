"""Order and invoice arithmetic (ARCHITECTURE.md §15). Decimal only; round half-up at line level.

Prices may be tax-inclusive (common in Nepali retail: the shelf price includes 13% VAT) or
tax-exclusive, per tenant setting. Shipping is not taxed in the MVP.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0")


def money(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LineInput:
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal
    tax_rate: Decimal  # percent, e.g. 13.00


@dataclass(frozen=True)
class LineAmounts:
    net: Decimal  # before tax, after discount
    tax_amount: Decimal
    line_total: Decimal  # what the customer pays for this line


@dataclass(frozen=True)
class Totals:
    subtotal: Decimal  # sum of net amounts
    discount_total: Decimal
    tax_total: Decimal
    shipping_fee: Decimal
    grand_total: Decimal


class InvalidLine(ValueError):
    pass


def line_amounts(line: LineInput, *, prices_include_tax: bool) -> LineAmounts:
    if line.quantity <= 0:
        raise InvalidLine("Quantity must be more than zero.")
    gross = money(line.quantity * line.unit_price)
    discount = money(line.discount_amount)
    if discount < 0 or discount > gross:
        raise InvalidLine("Discount can't be negative or more than the line amount.")
    after_discount = gross - discount
    rate = line.tax_rate / Decimal(100)
    if prices_include_tax:
        # Shelf price already contains the tax: split it out.
        net = money(after_discount / (1 + rate))
        tax = after_discount - net
        total = after_discount
    else:
        net = after_discount
        tax = money(after_discount * rate)
        total = net + tax
    return LineAmounts(net=net, tax_amount=tax, line_total=total)


def totals(lines: Iterable[tuple[LineInput, LineAmounts]], *, shipping_fee: Decimal = ZERO) -> Totals:
    subtotal = discount = tax = grand = ZERO
    for line, amounts in lines:
        subtotal += amounts.net
        discount += money(line.discount_amount)
        tax += amounts.tax_amount
        grand += amounts.line_total
    shipping = money(shipping_fee)
    if shipping < 0:
        raise InvalidLine("Delivery charge can't be negative.")
    return Totals(
        subtotal=subtotal, discount_total=discount, tax_total=tax, shipping_fee=shipping, grand_total=grand + shipping
    )


@dataclass(frozen=True)
class Balance:
    amount_paid: Decimal
    amount_due: Decimal
    payment_status: str


def balance(grand_total: Decimal, *, paid: Decimal, refunded: Decimal) -> Balance:
    """Balance rule from DATABASE.md §12; ``paid``/``refunded`` are sums of recorded (not voided) rows."""
    amount_paid = money(paid - refunded)
    amount_due = money(grand_total - amount_paid)
    if amount_paid > 0 and amount_due <= 0:
        status = "PAID"
    elif refunded > 0 and amount_paid <= 0:
        status = "REFUNDED"
    elif amount_paid > 0:
        status = "PARTIAL"
    else:
        status = "UNPAID"
    return Balance(amount_paid=amount_paid, amount_due=amount_due, payment_status=status)
