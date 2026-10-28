"""Phone normalization and extraction, Nepal-first (ARCHITECTURE.md §11).

Deliberately small and deterministic: E.164 for numbers we can place, ``None`` otherwise.
"""

import re

NEPAL_CC = "977"
# Nepali mobiles: 10 digits starting 96/97/98 (NTC, Ncell, Smart).
_NEPAL_MOBILE = re.compile(r"^9[678]\d{8}$")
# Candidate phone numbers inside free text: +977 98XXXXXXXX, 98XXXXXXXX, 977-98..., with spaces/dashes.
_IN_TEXT = re.compile(r"(?<!\d)(?:\+?977[\s-]?)?9[678](?:[\s-]?\d){8}(?!\d)")


def normalize(raw: str | None, *, default_cc: str = NEPAL_CC) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if raw.strip().startswith("00"):
        digits = digits[2:]
    if _NEPAL_MOBILE.match(digits) and default_cc == NEPAL_CC:
        return f"+{NEPAL_CC}{digits}"
    if digits.startswith(NEPAL_CC) and _NEPAL_MOBILE.match(digits[len(NEPAL_CC) :]):
        return f"+{digits}"
    # Already international (e.g. WhatsApp wa_id "9779812345678" or a foreign number).
    if 8 <= len(digits) <= 15 and (raw.strip().startswith("+") or len(digits) > 10):
        return f"+{digits}"
    return None


def extract(text: str | None) -> list[str]:
    """Normalized Nepali mobile numbers mentioned in a message, in order, without duplicates."""
    if not text:
        return []
    found: list[str] = []
    for match in _IN_TEXT.finditer(text):
        number = normalize(match.group(0))
        if number and number not in found:
            found.append(number)
    return found
