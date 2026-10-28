"""WhatsApp Cloud API adapter: webhook parsing (payload shapes from Meta's Cloud API webhook reference)."""

import hashlib
import hmac
import json
from collections.abc import Iterator

import pytest

from app.core.config import get_settings
from app.integrations.base import AccountEvent, InboundMessage, MessageStatusUpdate, Unsupported, WebhookRejected
from app.integrations.whatsapp.adapter import WhatsAppAdapter

SECRET, WABA, PHONE_ID, CUSTOMER = "wa-app-secret", "102290129340398", "106540352242922", "9779812345678"


@pytest.fixture(autouse=True)
def meta_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("META_APP_ID", "1234567890")
    monkeypatch.setenv("META_APP_SECRET", SECRET)
    monkeypatch.setenv("META_GRAPH_API_VERSION", "v99.0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


adapter = WhatsAppAdapter()


def _change(field: str, value: dict[str, object]) -> dict[str, object]:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": WABA, "changes": [{"field": field, "value": value}]}],
    }


def _messages_value(*messages: dict[str, object], statuses: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "9779800000000", "phone_number_id": PHONE_ID},
        "contacts": [{"profile": {"name": "Ram Sharma"}, "wa_id": CUSTOMER}],
        "messages": list(messages),
        **({"statuses": statuses} if statuses else {}),
    }


def test_signature_shared_with_messenger() -> None:
    body = json.dumps(_change("messages", _messages_value())).encode()
    good = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    adapter.validate_webhook({"x-hub-signature-256": good}, body)
    with pytest.raises(WebhookRejected):
        adapter.validate_webhook({"x-hub-signature-256": good}, body[:-1])


def test_text_message_carries_name_and_phone() -> None:
    (event,) = adapter.parse_webhook(
        _change(
            "messages",
            _messages_value(
                {
                    "from": CUSTOMER,
                    "id": "wamid.HBgM1",
                    "timestamp": "1761600000",
                    "type": "text",
                    "text": {"body": "Office chair ko price?"},
                    "context": {"from": "9779800000000", "id": "wamid.prev"},
                }
            ),
        )
    )
    assert isinstance(event, InboundMessage)
    assert event.channel_external_id == PHONE_ID and event.provider_user_id == CUSTOMER
    assert event.profile_name == "Ram Sharma" and event.phone == CUSTOMER
    assert event.text == "Office chair ko price?" and event.reply_to_provider_message_id == "wamid.prev"


@pytest.mark.parametrize(
    ("message", "kind", "text"),
    [
        (
            {"type": "image", "image": {"id": "MEDIA1", "mime_type": "image/jpeg", "caption": "This one"}},
            "image",
            "This one",
        ),
        (
            {"type": "document", "document": {"id": "MEDIA2", "filename": "quote.pdf", "mime_type": "application/pdf"}},
            "document",
            None,
        ),
        (
            {"type": "audio", "audio": {"id": "MEDIA3", "mime_type": "audio/ogg; codecs=opus", "voice": True}},
            "audio",
            None,
        ),
        (
            {"type": "location", "location": {"latitude": 26.66, "longitude": 87.27, "name": "Itahari Chowk"}},
            "location",
            "Itahari Chowk",
        ),
        (
            {
                "type": "interactive",
                "interactive": {"type": "button_reply", "button_reply": {"id": "yes", "title": "Yes, order"}},
            },
            "interactive",
            "Yes, order",
        ),
        ({"type": "reaction", "reaction": {"message_id": "wamid.x", "emoji": "👍"}}, "reaction", "👍"),
        ({"type": "unknown"}, "unsupported", None),
    ],
)
def test_message_types(message: dict[str, object], kind: str, text: str | None) -> None:
    (event,) = adapter.parse_webhook(
        _change("messages", _messages_value({"from": CUSTOMER, "id": "wamid.T", "timestamp": "1761600000", **message}))
    )
    assert isinstance(event, InboundMessage)
    assert event.message_type == kind and event.text == text
    if kind in ("image", "document", "audio"):
        assert event.media and event.media[0].provider_media_id.startswith("MEDIA")


def test_statuses_including_failure() -> None:
    value = {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": PHONE_ID},
        "statuses": [
            {"id": "wamid.out1", "status": "delivered", "timestamp": "1761600100", "recipient_id": CUSTOMER},
            {
                "id": "wamid.out2",
                "status": "failed",
                "timestamp": "1761600200",
                "recipient_id": CUSTOMER,
                "errors": [{"code": 131047, "title": "Re-engagement message"}],
            },
        ],
    }
    delivered, failed = adapter.parse_webhook(_change("messages", value))
    assert isinstance(delivered, MessageStatusUpdate) and delivered.status == "delivered"
    assert isinstance(failed, MessageStatusUpdate) and failed.status == "failed"
    assert failed.error_code == "131047" and failed.error_message == "Re-engagement message"


def test_coexistence_echo_is_outbound_to_customer() -> None:
    (event,) = adapter.parse_webhook(
        _change(
            "smb_message_echoes",
            {
                "messaging_product": "whatsapp",
                "metadata": {"phone_number_id": PHONE_ID},
                "message_echoes": [
                    {
                        "from": "9779800000000",
                        "to": CUSTOMER,
                        "id": "wamid.echo",
                        "timestamp": "1761600300",
                        "type": "text",
                        "text": {"body": "Sent from the app"},
                    }
                ],
            },
        )
    )
    assert isinstance(event, InboundMessage) and event.is_echo and event.provider_user_id == CUSTOMER


def test_account_events_and_unknown_fields() -> None:
    name, other = adapter.parse_webhook(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": WABA,
                    "changes": [
                        {
                            "field": "phone_number_name_update",
                            "value": {
                                "display_phone_number": "9779800000000",
                                "decision": "APPROVED",
                                "requested_verified_name": "Sharma Furniture",
                            },
                        },
                        {"field": "message_template_status_update", "value": {}},
                    ],
                }
            ],
        }
    )
    assert (
        isinstance(name, AccountEvent) and name.channel_external_id == WABA and name.kind == "phone_number_name_update"
    )
    assert isinstance(other, Unsupported)
    (wrong,) = adapter.parse_webhook({"object": "page", "entry": []})
    assert isinstance(wrong, Unsupported)
