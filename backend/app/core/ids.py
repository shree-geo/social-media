"""UUIDv7 identifiers, generated in the application (see DATABASE.md §1)."""

import uuid

from uuid_utils.compat import uuid7


def new_id() -> uuid.UUID:
    """Time-ordered UUIDv7 as a standard ``uuid.UUID``."""
    return uuid7()
