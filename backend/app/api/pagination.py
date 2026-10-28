"""Opaque keyset cursors (ARCHITECTURE.md §16): ``(timestamp, id)`` pairs, base64-encoded."""

import base64
import uuid
from datetime import datetime

from app.core.exceptions import AppError


class InvalidCursor(AppError):
    status, code, title = 400, "invalid_cursor", "Invalid cursor"


def encode(timestamp: datetime | None, row_id: uuid.UUID) -> str:
    raw = f"{timestamp.isoformat() if timestamp else ''}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode(cursor: str) -> tuple[datetime | None, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, _, row_id = raw.partition("|")
        return (datetime.fromisoformat(stamp) if stamp else None), uuid.UUID(row_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursor() from exc
