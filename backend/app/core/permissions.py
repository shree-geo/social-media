"""Permission codes and the system role matrix (ARCHITECTURE.md §7).

This module is the single source for seeding ``permissions``, ``roles`` and
``role_permissions``. Authorization checks always read the database, so a
tenant's effective permissions are whatever the seeded rows say.
"""

from typing import Final

PERMISSIONS: Final[dict[str, str]] = {
    "conversation.read": "View conversations and messages",
    "conversation.write": "Reply to and assign conversations",
    "customer.read": "View customers",
    "customer.write": "Create and edit customers",
    "customer.merge": "Merge and unmerge duplicate customers",
    "product.read": "View products",
    "product.write": "Create and edit products and stock",
    "order.read": "View orders",
    "order.write": "Create and edit orders",
    "invoice.read": "View invoices",
    "invoice.write": "Issue and cancel invoices",
    "delivery.read": "View deliveries",
    "delivery.write": "Record and update deliveries",
    "payment.read": "View payments",
    "payment.write": "Record and void payments",
    "report.read": "View dashboard and reports",
    "channel.manage": "Connect and disconnect channels",
    "user.manage": "Add, edit and disable users",
    "settings.manage": "Change business settings",
    "subscription.read": "View the subscription and receipts",
    "audit.read": "View the audit log",
}

_ALL = frozenset(PERMISSIONS)
_READ_ALL = frozenset(code for code in PERMISSIONS if code.endswith(".read")) - {"subscription.read", "audit.read"}

ROLE_NAMES: Final[dict[str, str]] = {
    "OWNER": "Owner",
    "ADMIN": "Admin",
    "MANAGER": "Manager",
    "SALES": "Sales",
    "DELIVERY": "Delivery",
    "ACCOUNTANT": "Accountant",
    "VIEWER": "Viewer",
}

ROLE_PERMISSIONS: Final[dict[str, frozenset[str]]] = {
    "OWNER": _ALL,
    "ADMIN": _ALL,
    "MANAGER": _READ_ALL
    | {
        "conversation.write",
        "customer.write",
        "customer.merge",
        "product.write",
        "order.write",
        "invoice.write",
        "delivery.write",
        "payment.write",
    },
    "SALES": frozenset(
        {
            "conversation.read",
            "conversation.write",
            "customer.read",
            "customer.write",
            "product.read",
            "order.read",
            "order.write",
            "invoice.read",
            "delivery.read",
        }
    ),
    # payment.write for DELIVERY is limited to COD on their own deliveries (enforced in the payment service).
    "DELIVERY": frozenset(
        {"customer.read", "product.read", "order.read", "delivery.read", "delivery.write", "payment.write"}
    ),
    "ACCOUNTANT": frozenset(
        {
            "customer.read",
            "product.read",
            "order.read",
            "invoice.read",
            "invoice.write",
            "payment.read",
            "payment.write",
            "report.read",
            "subscription.read",
        }
    ),
    "VIEWER": _READ_ALL,
}

# Only an OWNER may grant or remove OWNER; a tenant always keeps at least one active OWNER.
OWNER_ROLE: Final = "OWNER"
