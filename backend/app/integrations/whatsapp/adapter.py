"""WhatsApp Business Platform, Cloud API (ARCHITECTURE.md §9).

Webhooks follow Meta's Cloud API reference: ``object: "whatsapp_business_account"``,
``entry[].changes[]`` keyed by ``field``:

* ``messages``            → ``value.messages[]`` (customer messages, with ``value.contacts[]``)
                            and ``value.statuses[]`` (our messages: sent/delivered/read/failed)
* ``smb_message_echoes``  → messages the business sent from the WhatsApp Business app (coexistence)
* ``phone_number_quality_update`` / ``phone_number_name_update`` / ``account_update`` → account events

``entry[].id`` is the WhatsApp Business Account (WABA) id; messages are routed by
``value.metadata.phone_number_id``.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar

from app.integrations.base import (
    AccountEvent,
    ChannelAccountRef,
    InboundMessage,
    MediaRef,
    MessageStatusUpdate,
    MessageType,
    NormalizedEvent,
    OutboundText,
    PermanentSendError,
    SendResult,
    SocialChannelAdapter,
    TransientSendError,
    Unsupported,
)
from app.integrations.meta import graph
from app.integrations.meta import webhooks as meta_webhooks

_MEDIA_TYPES: dict[str, MessageType] = {
    "image": "image",
    "video": "video",
    "audio": "audio",
    "voice": "audio",
    "document": "document",
    "sticker": "sticker",
}

# Cloud API error codes that must not be retried, mapped to our codes.
_PERMANENT_SEND = {
    131047: "window_closed",  # more than 24h since the customer's last message
    131026: "recipient_unavailable",  # not on WhatsApp / old app / blocked us
    131051: "unsupported_message",
    131052: "media_unavailable",
    131021: "invalid_recipient",  # sending to our own number
}
_TRANSIENT_SEND = frozenset(
    {130429, 131056, 131000, 131016}
)  # throughput, pair rate limit, generic, service unavailable

ACCOUNT_FIELDS = frozenset({"phone_number_quality_update", "phone_number_name_update", "account_update"})


def _ts(seconds: str | int | None) -> datetime:
    try:
        return datetime.fromtimestamp(int(seconds or 0), UTC) if seconds else datetime.now(UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


def _text_and_type(message: Mapping[str, Any]) -> tuple[MessageType, str | None, tuple[MediaRef, ...], dict[str, Any]]:
    kind = str(message.get("type", ""))
    if kind == "text":
        return "text", (message.get("text") or {}).get("body"), (), {}
    if kind in _MEDIA_TYPES:
        media = message.get(kind) or {}
        ref = MediaRef(
            provider_media_id=str(media.get("id", "")),
            mime_type=media.get("mime_type"),
            filename=media.get("filename"),
            caption=media.get("caption"),
        )
        return _MEDIA_TYPES[kind], media.get("caption"), (ref,) if ref.provider_media_id else (), {}
    if kind == "location":
        loc = message.get("location") or {}
        label = ", ".join(str(v) for v in (loc.get("name"), loc.get("address")) if v) or "Shared a location"
        return (
            "location",
            label,
            (),
            {"location": {k: loc.get(k) for k in ("latitude", "longitude", "name", "address")}},
        )
    if kind == "contacts":
        names = [((c.get("name") or {}).get("formatted_name")) for c in message.get("contacts") or []]
        return (
            "contacts",
            "Shared contact: " + ", ".join(n for n in names if n),
            (),
            {"contacts": message.get("contacts")},
        )
    if kind == "interactive":
        reply = message.get("interactive") or {}
        chosen = reply.get("button_reply") or reply.get("list_reply") or {}
        return "interactive", chosen.get("title"), (), {"reply_id": chosen.get("id")}
    if kind == "button":  # quick-reply button on a template
        return "interactive", (message.get("button") or {}).get("text"), (), {}
    if kind == "reaction":
        reaction = message.get("reaction") or {}
        return "reaction", reaction.get("emoji"), (), {"reacted_to": reaction.get("message_id")}
    return "unsupported", None, (), {"type": kind}


class WhatsAppAdapter(SocialChannelAdapter):
    provider: ClassVar[str] = "whatsapp"

    def verify_subscription_challenge(self, params: Mapping[str, str]) -> str | None:
        return meta_webhooks.verify_subscription_challenge(params)

    def validate_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> None:
        meta_webhooks.validate_signature(headers, raw_body)

    def parse_webhook(self, payload: Mapping[str, Any]) -> list[NormalizedEvent]:
        if payload.get("object") != "whatsapp_business_account":
            return [Unsupported(None, f"object {payload.get('object')!r}")]
        events: list[NormalizedEvent] = []
        for entry in payload.get("entry") or []:
            waba_id = str(entry.get("id", ""))
            for change in entry.get("changes") or []:
                field, value = change.get("field"), change.get("value") or {}
                if field == "messages":
                    events.extend(self._messages(value))
                elif field == "smb_message_echoes":
                    events.extend(self._echoes(value))
                elif field in ACCOUNT_FIELDS:
                    events.append(AccountEvent(waba_id, str(field), dict(value)))
                else:
                    events.append(Unsupported(waba_id, f"field {field!r}"))
        return events

    def _messages(self, value: Mapping[str, Any]) -> list[NormalizedEvent]:
        phone_number_id = str((value.get("metadata") or {}).get("phone_number_id", ""))
        names = {str(c.get("wa_id")): (c.get("profile") or {}).get("name") for c in value.get("contacts") or []}
        events: list[NormalizedEvent] = []
        for message in value.get("messages") or []:
            sender = str(message.get("from", ""))
            message_type, text, media, extra = _text_and_type(message)
            events.append(
                InboundMessage(
                    channel_external_id=phone_number_id,
                    provider_user_id=sender,
                    provider_message_id=str(message.get("id", "")),
                    timestamp=_ts(message.get("timestamp")),
                    message_type=message_type,
                    text=text,
                    media=media,
                    reply_to_provider_message_id=(message.get("context") or {}).get("id"),
                    profile_name=names.get(sender),
                    phone=sender,  # wa_id is the customer's number today (usernames may change this)
                    extra=extra,
                )
            )
        for status in value.get("statuses") or []:
            error = (status.get("errors") or [{}])[0]
            events.append(
                MessageStatusUpdate(
                    channel_external_id=phone_number_id,
                    provider_message_id=str(status.get("id", "")),
                    status=status.get("status", "sent"),
                    timestamp=_ts(status.get("timestamp")),
                    error_code=str(error["code"]) if error.get("code") else None,
                    error_message=error.get("title") or error.get("message"),
                )
            )
        return events

    def _echoes(self, value: Mapping[str, Any]) -> list[NormalizedEvent]:
        phone_number_id = str((value.get("metadata") or {}).get("phone_number_id", ""))
        events: list[NormalizedEvent] = []
        for message in value.get("message_echoes") or []:
            message_type, text, media, extra = _text_and_type(message)
            events.append(
                InboundMessage(
                    channel_external_id=phone_number_id,
                    provider_user_id=str(message.get("to", "")),
                    provider_message_id=str(message.get("id", "")),
                    timestamp=_ts(message.get("timestamp")),
                    message_type=message_type,
                    text=text,
                    media=media,
                    is_echo=True,
                    extra=extra,
                )
            )
        return events

    async def send_text(self, account: ChannelAccountRef, to: str, message: OutboundText) -> SendResult:
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": message.text},
        }
        if message.reply_to_provider_message_id:
            body["context"] = {"message_id": message.reply_to_provider_message_id}
        try:
            data = await graph.post(f"/{account.external_account_id}/messages", token=account.access_token, json=body)
        except graph.GraphError as exc:
            if exc.transient or exc.code in _TRANSIENT_SEND:
                raise TransientSendError(str(exc), code=exc.short_code) from None
            code = "token_invalid" if exc.token_invalid else _PERMANENT_SEND.get(exc.code or 0, exc.short_code)
            raise PermanentSendError(exc.message, code=code) from None
        messages = data.get("messages") or []
        if not messages or not messages[0].get("id"):
            raise TransientSendError("Meta did not return a message id")
        return SendResult(provider_message_id=str(messages[0]["id"]))
