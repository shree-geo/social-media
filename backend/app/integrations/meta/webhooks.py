"""Webhook checks shared by every Meta product (Messenger, WhatsApp): one app, one secret."""

import hashlib
import hmac
from collections.abc import Mapping

from app.core.config import get_settings
from app.integrations.base import WebhookRejected


def verify_subscription_challenge(params: Mapping[str, str]) -> str | None:
    """GET handshake when the callback URL is saved in the Meta dashboard."""
    expected = get_settings().meta_webhook_verify_token
    if (
        expected
        and params.get("hub.mode") == "subscribe"
        and hmac.compare_digest(params.get("hub.verify_token", ""), expected)
    ):
        return params.get("hub.challenge")
    return None


def validate_signature(headers: Mapping[str, str], raw_body: bytes) -> None:
    """``X-Hub-Signature-256: sha256=<HMAC of the raw body with the app secret>``."""
    signature = headers.get("x-hub-signature-256", "")
    if not signature.startswith("sha256="):
        raise WebhookRejected("missing X-Hub-Signature-256")
    secret = get_settings().meta_app_secret.encode()
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    if not secret or not hmac.compare_digest(signature.removeprefix("sha256="), expected):
        raise WebhookRejected("signature mismatch")
