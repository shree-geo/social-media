"""Meta ``signed_request`` (deauthorize and data-deletion callbacks).

Format: ``<base64url HMAC-SHA256 signature>.<base64url JSON payload>``, signed with the app secret.
"""

import base64
import hashlib
import hmac
import json
from typing import Any

from app.core.config import get_settings


class InvalidSignedRequest(Exception):
    pass


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def parse(signed_request: str) -> dict[str, Any]:
    try:
        encoded_sig, payload = signed_request.split(".", 1)
        signature = _b64decode(encoded_sig)
        data = json.loads(_b64decode(payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise InvalidSignedRequest("malformed signed_request") from exc
    if not isinstance(data, dict) or str(data.get("algorithm", "")).upper() != "HMAC-SHA256":
        raise InvalidSignedRequest("unexpected algorithm")
    secret = get_settings().meta_app_secret.encode()
    expected = hmac.new(secret, payload.encode(), hashlib.sha256).digest()
    if not secret or not hmac.compare_digest(signature, expected):
        raise InvalidSignedRequest("bad signature")
    return data
