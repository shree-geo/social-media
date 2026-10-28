"""Messenger adapter: webhook verification and parsing (payload shapes from Meta's Messenger Platform reference)."""

import base64
import hashlib
import hmac
import json
from collections.abc import Iterator

import pytest

from app.core.config import get_settings
from app.integrations.base import InboundMessage, MessageStatusUpdate, ReadReceipt, Unsupported, WebhookRejected
from app.integrations.messenger.adapter import MessengerAdapter
from app.integrations.meta import graph, signed_request

APP_ID, SECRET, PAGE, PSID = "1234567890", "test-app-secret", "PAGE_1", "PSID_1"


@pytest.fixture(autouse=True)
def meta_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("META_APP_ID", APP_ID)
    monkeypatch.setenv("META_APP_SECRET", SECRET)
    monkeypatch.setenv("META_GRAPH_API_VERSION", "v99.0")
    monkeypatch.setenv("META_WEBHOOK_VERIFY_TOKEN", "verify-me-please")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _signature(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _payload(*messaging: dict[str, object]) -> dict[str, object]:
    return {"object": "page", "entry": [{"id": PAGE, "time": 1761600000000, "messaging": list(messaging)}]}


adapter = MessengerAdapter()


def test_signature_valid_and_tampered() -> None:
    body = json.dumps(_payload()).encode()
    adapter.validate_webhook({"x-hub-signature-256": _signature(body)}, body)
    with pytest.raises(WebhookRejected):
        adapter.validate_webhook({"x-hub-signature-256": _signature(body)}, body + b" ")
    with pytest.raises(WebhookRejected):
        adapter.validate_webhook({}, body)


def test_subscription_challenge() -> None:
    ok = {"hub.mode": "subscribe", "hub.verify_token": "verify-me-please", "hub.challenge": "42"}
    assert adapter.verify_subscription_challenge(ok) == "42"
    assert adapter.verify_subscription_challenge({**ok, "hub.verify_token": "nope"}) is None
    assert adapter.verify_subscription_challenge({**ok, "hub.mode": "unsubscribe"}) is None


def test_parse_text_message_with_reply() -> None:
    (event,) = adapter.parse_webhook(
        _payload(
            {
                "sender": {"id": PSID},
                "recipient": {"id": PAGE},
                "timestamp": 1761600000123,
                "message": {"mid": "m_1", "text": "Kati ho?", "reply_to": {"mid": "m_0"}},
            }
        )
    )
    assert isinstance(event, InboundMessage)
    assert (event.channel_external_id, event.provider_user_id, event.provider_message_id) == (PAGE, PSID, "m_1")
    assert event.text == "Kati ho?" and event.reply_to_provider_message_id == "m_0" and not event.is_echo
    assert event.timestamp.year == 2025


def test_parse_attachment_only_message() -> None:
    (event,) = adapter.parse_webhook(
        _payload(
            {
                "sender": {"id": PSID},
                "recipient": {"id": PAGE},
                "timestamp": 1761600000123,
                "message": {"mid": "m_2", "attachments": [{"type": "image", "payload": {"url": "https://cdn/x.jpg"}}]},
            }
        )
    )
    assert isinstance(event, InboundMessage)
    assert event.message_type == "image" and event.media[0].provider_media_id == "https://cdn/x.jpg"


def test_echo_from_our_app_is_skipped_but_page_inbox_echo_is_kept() -> None:
    ours = {"mid": "m_3", "text": "hi", "is_echo": True, "app_id": int(APP_ID)}
    theirs = {"mid": "m_4", "text": "sent from Page inbox", "is_echo": True, "app_id": 263902037430900}
    events = adapter.parse_webhook(
        _payload(
            {"sender": {"id": PAGE}, "recipient": {"id": PSID}, "timestamp": 1, "message": ours},
            {"sender": {"id": PAGE}, "recipient": {"id": PSID}, "timestamp": 2, "message": theirs},
        )
    )
    assert len(events) == 1
    echo = events[0]
    assert isinstance(echo, InboundMessage) and echo.is_echo and echo.provider_user_id == PSID


def test_delivery_read_and_postback() -> None:
    delivery, read, postback = adapter.parse_webhook(
        _payload(
            {
                "sender": {"id": PSID},
                "recipient": {"id": PAGE},
                "delivery": {"mids": ["m_9"], "watermark": 1761600000000},
            },
            {"sender": {"id": PSID}, "recipient": {"id": PAGE}, "timestamp": 5, "read": {"watermark": 1761600000500}},
            {
                "sender": {"id": PSID},
                "recipient": {"id": PAGE},
                "timestamp": 6,
                "postback": {"title": "Get started", "payload": "GS"},
            },
        )
    )
    assert (
        isinstance(delivery, MessageStatusUpdate) and delivery.status == "delivered" and not delivery.retry_if_unknown
    )
    assert isinstance(read, ReadReceipt) and read.provider_user_id == PSID
    assert (
        isinstance(postback, InboundMessage)
        and postback.text == "Get started"
        and postback.message_type == "interactive"
    )


def test_non_page_object_is_unsupported() -> None:
    (event,) = adapter.parse_webhook({"object": "whatsapp_business_account", "entry": []})
    assert isinstance(event, Unsupported)


def _signed(payload: dict[str, object], secret: str = SECRET) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = (
        base64.urlsafe_b64encode(hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest())
        .decode()
        .rstrip("=")
    )
    return f"{sig}.{encoded}"


def test_signed_request() -> None:
    assert signed_request.parse(_signed({"algorithm": "HMAC-SHA256", "user_id": "u1"}))["user_id"] == "u1"
    with pytest.raises(signed_request.InvalidSignedRequest):
        signed_request.parse(_signed({"algorithm": "HMAC-SHA256", "user_id": "u1"}, secret="other"))
    with pytest.raises(signed_request.InvalidSignedRequest):
        signed_request.parse("garbage")


@pytest.mark.parametrize(
    ("error", "transient", "token_invalid"),
    [
        (graph.GraphError("rate", code=613, http_status=400), True, False),
        (graph.GraphError("down", http_status=503), True, False),
        (graph.GraphError("network"), True, False),
        (graph.GraphError("expired", code=190, http_status=400), False, True),
        (graph.GraphError("window", code=10, subcode=2018278, http_status=400), False, False),
    ],
)
def test_graph_error_classification(error: graph.GraphError, transient: bool, token_invalid: bool) -> None:
    assert error.transient is transient and error.token_invalid is token_invalid


def test_appsecret_proof_is_hmac_of_token() -> None:
    assert graph.appsecret_proof("tok") == hmac.new(SECRET.encode(), b"tok", hashlib.sha256).hexdigest()
