"""Invoices: issue from an order, cancel, PDF (ARCHITECTURE.md §15).

* Issuing copies the order's lines and freezes seller/buyer details (snapshots); after that
  the invoice is immutable (database trigger) — corrections are cancel + issue a new one.
* Numbers come from ``document_sequences`` per tenant and period (calendar or Nepali fiscal year).
* The PDF is rendered with WeasyPrint (HarfBuzz shaping, bundled Noto fonts, so Devanagari
  names print correctly) and stored in object storage.

Nepal IRD format compliance must be reviewed with an accountant before go-live (ARCHITECTURE.md §25).
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, NotFound
from app.models import Customer, Invoice, InvoiceItem, Order, StoredObject, Tenant, TenantSettings
from app.services import audit, numbering, orders, storage
from app.services.amount_words import rupees_in_words
from app.services.audit import RequestInfo
from app.services.subscriptions import tenant_today

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"


class InvoiceNotAllowed(AppError):
    status, code, title = 409, "invoice_not_allowed", "An invoice can't be issued for this order"


def _seller(tenant: Tenant) -> dict[str, Any]:
    return {
        "business_name": tenant.business_name,
        "legal_name": tenant.legal_name,
        "tax_number": tenant.tax_number,
        "vat_registered": tenant.vat_registered,
        "address": tenant.address,
        "phone": tenant.phone,
        "email": tenant.email,
    }


def _buyer(customer: Customer, order: Order) -> dict[str, Any]:
    return {
        "name": customer.display_name,
        "phone": customer.phone_e164,
        "email": customer.email,
        "address": order.delivery_address,
    }


async def issue_from_order(
    session: AsyncSession, *, tenant_id: uuid.UUID, order_id: uuid.UUID, user_id: uuid.UUID, request: RequestInfo
) -> Invoice:
    order = (await session.execute(select(Order).where(Order.id == order_id).with_for_update())).scalar_one_or_none()
    if order is None:
        raise NotFound()
    if order.status in ("CANCELLED", "REJECTED"):
        raise InvoiceNotAllowed("This order was cancelled.")
    live = (
        await session.execute(
            select(Invoice.invoice_number).where(Invoice.order_id == order.id, Invoice.status != "CANCELLED")
        )
    ).scalar_one_or_none()
    if live:
        raise Conflict(f"Invoice {live} already exists for this order.", code="invoice_exists")

    tenant = await session.get(Tenant, tenant_id)
    settings = await session.get(TenantSettings, tenant_id)
    customer = await session.get(Customer, order.customer_id)
    assert tenant is not None and customer is not None
    today = tenant_today(tenant.timezone)
    due_days = settings.default_payment_due_days if settings else 0

    invoice = Invoice(
        tenant_id=tenant_id,
        order_id=order.id,
        customer_id=order.customer_id,
        status="DRAFT",  # lines may only be added while DRAFT (trigger); issued just below
        currency=order.currency,
        subtotal=order.subtotal,
        discount_total=order.discount_total,
        tax_total=order.tax_total,
        shipping_fee=order.shipping_fee,
        grand_total=order.grand_total,
        amount_paid=order.amount_paid,
        amount_due=order.grand_total - order.amount_paid,
        payment_status=order.payment_status,
        seller_snapshot=_seller(tenant),
        buyer_snapshot=_buyer(customer, order),
    )
    session.add(invoice)
    await session.flush()
    for item in await orders.order_items(session, order.id):
        session.add(
            InvoiceItem(
                tenant_id=tenant_id,
                invoice_id=invoice.id,
                order_item_id=item.id,
                description=item.product_name,
                sku=item.sku,
                unit=item.unit,
                quantity=item.quantity,
                unit_price=item.unit_price,
                discount_amount=item.discount_amount,
                tax_rate=item.tax_rate,
                tax_amount=item.tax_amount,
                line_total=item.line_total,
                position=item.position,
            )
        )
    await session.flush()
    invoice.invoice_number = await numbering.next_number(
        session, tenant_id, "INV", numbering.period_key(tenant.numbering_period, today)
    )
    invoice.status = "ISSUED"
    invoice.issue_date = today
    invoice.due_date = today + timedelta(days=due_days)
    invoice.issued_by = user_id
    invoice.issued_at = datetime.now(UTC)
    await session.flush()
    await audit.record(
        session,
        action="INVOICE_ISSUED",
        actor_type="user",
        actor_id=user_id,
        tenant_id=tenant_id,
        resource_type="invoice",
        resource_id=invoice.id,
        after={
            "invoice_number": invoice.invoice_number,
            "order": order.order_number,
            "grand_total": str(invoice.grand_total),
        },
        request=request,
    )
    return invoice


async def cancel(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: str,
    request: RequestInfo,
) -> Invoice:
    invoice = (
        await session.execute(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    ).scalar_one_or_none()
    if invoice is None:
        raise NotFound()
    if invoice.status != "ISSUED":
        raise Conflict("Only an issued invoice can be cancelled.", code="invoice_not_issued")
    if invoice.amount_paid > 0:
        raise Conflict("This invoice has payments. Refund or void them first.", code="invoice_has_payments")
    invoice.status = "CANCELLED"
    invoice.cancelled_by, invoice.cancelled_at, invoice.cancel_reason = user_id, datetime.now(UTC), reason
    await audit.record(
        session,
        action="INVOICE_CANCELLED",
        actor_type="user",
        actor_id=user_id,
        tenant_id=tenant_id,
        resource_type="invoice",
        resource_id=invoice.id,
        after={"invoice_number": invoice.invoice_number, "reason": reason},
        request=request,
    )
    return invoice


# --- PDF ------------------------------------------------------------------------------------


def _fmt(value: Decimal) -> str:
    """1234567.5 → 12,34,567.50 (South Asian grouping)."""
    sign = "-" if value < 0 else ""
    whole, _, cents = f"{abs(value):.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return f"{sign}{whole}.{cents}"


def _qty(value: Decimal) -> str:
    return f"{value.normalize():f}"


def _address(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, dict):
        return ", ".join(str(v) for v in value.values() if v)
    return str(value)


def e(value: Any) -> str:
    """HTML-escape for the invoice template; empty for missing values."""
    return escape(str(value)) if value else ""


def render_html(invoice: Invoice, items: list[InvoiceItem], footer: str | None) -> str:
    seller, buyer = invoice.seller_snapshot, invoice.buyer_snapshot
    title = "Tax Invoice" if seller.get("vat_registered") else "Invoice"
    title_ne = "कर बीजक" if seller.get("vat_registered") else "बीजक"
    rows = "".join(
        f"<tr><td>{i + 1}</td><td>{e(item.description)}<div class='sku'>{e(item.sku)}</div></td>"
        f"<td class='num'>{_qty(item.quantity)} {e(item.unit)}</td><td class='num'>{_fmt(item.unit_price)}</td>"
        f"<td class='num'>{_fmt(item.discount_amount) if item.discount_amount else ''}</td>"
        f"<td class='num'>{_fmt(item.tax_rate)}%</td><td class='num'>{_fmt(item.line_total)}</td></tr>"
        for i, item in enumerate(items)
    )
    status_banner = "<div class='cancelled'>Cancelled</div>" if invoice.status == "CANCELLED" else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><style>
@font-face {{ font-family: Inv; src: url("{(FONTS / "NotoSans-Regular.ttf").as_uri()}"); }}
@font-face {{ font-family: Inv; font-weight: bold; src: url("{(FONTS / "NotoSans-Bold.ttf").as_uri()}"); }}
@font-face {{ font-family: InvDeva; src: url("{(FONTS / "NotoSansDevanagari-Regular.ttf").as_uri()}"); }}
@font-face {{ font-family: InvDeva; font-weight: bold; src: url("{(FONTS / "NotoSansDevanagari-Bold.ttf").as_uri()}"); }}
@page {{ size: A4; margin: 16mm 14mm; @bottom-center {{ content: "Page " counter(page) " of " counter(pages); font: 8pt Inv; color: #8a91ac; }} }}
body {{ font-family: Inv, InvDeva, sans-serif; font-size: 9.5pt; color: #1a2142; line-height: 1.45; }}
h1 {{ font-size: 16pt; margin: 0; color: #24306e; }} .muted {{ color: #545d80; }}
.head {{ display: flex; justify-content: space-between; border-bottom: 2px solid #24306e; padding-bottom: 8pt; }}
.parties {{ display: flex; justify-content: space-between; margin: 12pt 0; gap: 24pt; }}
.label {{ font-size: 8pt; color: #545d80; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 6pt; }}
th {{ background: #eceef5; text-align: left; font-size: 8.5pt; padding: 5pt; }}
td {{ border-bottom: 1px solid #dde1ec; padding: 5pt; vertical-align: top; }}
.num {{ text-align: right; white-space: nowrap; }} .sku {{ font-size: 7.5pt; color: #8a91ac; }}
.totals {{ margin-left: auto; width: 46%; margin-top: 8pt; }} .totals td {{ border: none; padding: 2pt 5pt; }}
.grand td {{ border-top: 2px solid #24306e; font-weight: bold; font-size: 11pt; }}
.words {{ margin-top: 10pt; font-style: italic; }}
.cancelled {{ color: #b93434; border: 2px solid #b93434; display: inline-block; padding: 2pt 8pt; font-weight: bold; }}
.footer {{ margin-top: 20pt; font-size: 8.5pt; color: #545d80; }}
</style></head><body>
<div class="head"><div><h1>{e(seller.get("business_name"))}</h1>
<div class="muted">{e(seller.get("legal_name"))}</div>
<div>{e(_address(seller.get("address")))}</div>
<div>{e(seller.get("phone"))} {e(seller.get("email"))}</div>
{"<div><b>PAN/VAT:</b> " + e(seller.get("tax_number")) + "</div>" if seller.get("tax_number") else ""}</div>
<div style="text-align:right"><h1>{title}</h1><div class="muted">{title_ne}</div>{status_banner}
<div><b>No.</b> {e(invoice.invoice_number)}</div><div><b>Date</b> {invoice.issue_date}</div>
{"<div><b>Due</b> " + str(invoice.due_date) + "</div>" if invoice.due_date and invoice.due_date != invoice.issue_date else ""}</div></div>
<div class="parties"><div><div class="label">Bill to</div><b>{e(buyer.get("name"))}</b>
<div>{e(buyer.get("phone"))}</div><div>{e(_address(buyer.get("address")))}</div>
{"<div>PAN: " + e(buyer.get("tax_number")) + "</div>" if buyer.get("tax_number") else ""}</div></div>
<table><thead><tr><th>#</th><th>Description</th><th class="num">Qty</th><th class="num">Rate</th><th class="num">Discount</th>
<th class="num">VAT</th><th class="num">Amount</th></tr></thead><tbody>{rows}</tbody></table>
<table class="totals">
<tr><td>Taxable amount</td><td class="num">{_fmt(invoice.subtotal)}</td></tr>
<tr><td>VAT</td><td class="num">{_fmt(invoice.tax_total)}</td></tr>
{"<tr><td>Delivery</td><td class='num'>" + _fmt(invoice.shipping_fee) + "</td></tr>" if invoice.shipping_fee else ""}
<tr class="grand"><td>Total ({e(invoice.currency)})</td><td class="num">{_fmt(invoice.grand_total)}</td></tr></table>
<div class="words">{rupees_in_words(invoice.grand_total)}</div>
<div class="footer">{e(footer)}</div>
</body></html>"""


def _render_pdf(html_text: str) -> bytes:
    from weasyprint import HTML  # heavy import; only in processes that render

    pdf: bytes = HTML(string=html_text).write_pdf()
    return pdf


async def pdf_bytes(session: AsyncSession, invoice: Invoice) -> bytes:
    """The stored PDF, rendering and storing it first if it doesn't exist yet."""
    if invoice.pdf_object_id:
        stored = await session.get(StoredObject, invoice.pdf_object_id)
        if stored is not None:
            return await storage.get(stored)
    items = list(
        (
            await session.execute(
                select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id).order_by(InvoiceItem.position)
            )
        ).scalars()
    )
    settings = await session.get(TenantSettings, invoice.tenant_id)
    data = await asyncio.to_thread(
        _render_pdf, render_html(invoice, items, settings.invoice_footer if settings else None)
    )
    saved = await storage.put(
        session,
        tenant_id=invoice.tenant_id,
        data=data,
        content_type="application/pdf",
        purpose="invoice_pdf",
        key_prefix="invoices",
        extension="pdf",
    )
    invoice.pdf_object_id = saved.object_id
    return data
