"""Facebook Messenger (Messenger Platform webhooks + Send API) — ARCHITECTURE.md §9.

Payload shapes follow Meta's Messenger Platform webhook reference: ``object: "page"``,
``entry[].messaging[]`` with ``message`` / ``delivery`` / ``read`` / ``postback``.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar

from app.core.config import get_settings
from app.integrations.base import (
    ChannelAccountRef,
    CustomerProfile,
    InboundMessage,
    MediaRef,
    MessageStatusUpdate,
    MessageType,
    NormalizedEvent,
    OutboundText,
    PermanentSendError,
    ReadReceipt,
    SendResult,
    SocialChannelAdapter,
    TransientSendError,
    Unsupported,
)
from app.integrations.meta import graph
from app.integrations.meta import webhooks as meta_webhooks

# Messenger attachment types → our message types.
_ATTACHMENT_TYPES: dict[str, MessageType] = {
    "image": "image",
    "video": "video",
    "audio": "audio",
    "file": "document",
    "location": "location",
    "template": "interactive",
    "fallback": "unsupported",
}

# Fields our app subscribes each Page to (ONBOARDING_AND_CHANNEL_SETUP.md §6).
PAGE_SUBSCRIBED_FIELDS = ("messages", "message_echoes", "message_deliveries", "message_reads", "messaging_postbacks")

# Send API errors meaning "don't retry": outside the 24h window, user unavailable/blocked.
_PERMANENT_SEND = {
    (10, 2018278): "window_closed",
    (551, None): "recipient_unavailable",
    (200, None): "permission_denied",
}


def _ts(ms: int | float | None) -> datetime:
    return datetime.fromtimestamp((ms or 0) / 1000, UTC) if ms else datetime.now(UTC)


class MessengerAdapter(SocialChannelAdapter):
    provider: ClassVar[str] = "messenger"

    # --- webhooks -------------------------------------------------------------------

    def verify_subscription_challenge(self, params: Mapping[str, str]) -> str | None:
        return meta_webhooks.verify_subscription_challenge(params)

    def validate_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> None:
        meta_webhooks.validate_signature(headers, raw_body)

    def parse_webhook(self, payload: Mapping[str, Any]) -> list[NormalizedEvent]:
        if payload.get("object") != "page":
            return [Unsupported(None, f"object {payload.get('object')!r}")]
        our_app_id = str(get_settings().meta_app_id)
        events: list[NormalizedEvent] = []
        for entry in payload.get("entry") or []:
            page_id = str(entry.get("id", ""))
            for item in entry.get("messaging") or []:
                events.extend(self._parse_item(page_id, item, our_app_id))
        return events

    def _parse_item(self, page_id: str, item: Mapping[str, Any], our_app_id: str) -> list[NormalizedEvent]:
        sender = str((item.get("sender") or {}).get("id", ""))
        recipient = str((item.get("recipient") or {}).get("id", ""))

        if "message" in item:
            message = item["message"]
            echo = bool(message.get("is_echo"))
            if echo and str(message.get("app_id", "")) == our_app_id:
                # Our own reply coming back: already stored by the send path.
                return []
            customer = recipient if echo else sender
            attachments = message.get("attachments") or []
            media = tuple(
                MediaRef(
                    provider_media_id=str((a.get("payload") or {}).get("url") or ""),
                    mime_type=a.get("type"),
                )
                for a in attachments
                if (a.get("payload") or {}).get("url")
            )
            message_type: MessageType = "text"
            if message.get("text") is None and attachments:
                message_type = _ATTACHMENT_TYPES.get(attachments[0].get("type", ""), "unsupported")
            return [
                InboundMessage(
                    channel_external_id=page_id,
                    provider_user_id=customer,
                    provider_message_id=str(message.get("mid", "")),
                    timestamp=_ts(item.get("timestamp")),
                    message_type=message_type,
                    text=message.get("text"),
                    media=media,
                    reply_to_provider_message_id=(message.get("reply_to") or {}).get("mid"),
                    is_echo=echo,
                    extra={"quick_reply": message["quick_reply"]} if message.get("quick_reply") else {},
                )
            ]

        if "postback" in item:
            postback = item["postback"]
            return [
                InboundMessage(
                    channel_external_id=page_id,
                    provider_user_id=sender,
                    provider_message_id=str(postback.get("mid") or f"postback.{sender}.{item.get('timestamp')}"),
                    timestamp=_ts(item.get("timestamp")),
                    message_type="interactive",
                    text=postback.get("title"),
                    extra={"postback_payload": postback.get("payload")},
                )
            ]

        if "delivery" in item:
            delivery = item["delivery"]
            return [
                MessageStatusUpdate(
                    channel_external_id=page_id,
                    provider_message_id=str(mid),
                    status="delivered",
                    timestamp=_ts(delivery.get("watermark")),
                    retry_if_unknown=False,  # receipts also cover messages sent before we connected
                )
                for mid in delivery.get("mids") or []
            ]

        if "read" in item:
            return [ReadReceipt(page_id, sender, _ts((item["read"] or {}).get("watermark")))]

        return [Unsupported(page_id, "unhandled messaging event")]

    # --- sending ----------------------------------------------------------------------

    async def send_text(self, account: ChannelAccountRef, to: str, message: OutboundText) -> SendResult:
        body: dict[str, Any] = {
            "recipient": {"id": to},
            "messaging_type": "RESPONSE",  # reply inside the 24h standard messaging window
            "message": {"text": message.text},
        }
        try:
            data = await graph.post(f"/{account.external_account_id}/messages", token=account.access_token, json=body)
        except graph.GraphError as exc:
            if exc.transient:
                raise TransientSendError(str(exc), code=exc.short_code) from None
            code = _PERMANENT_SEND.get((exc.code or 0, exc.subcode)) or _PERMANENT_SEND.get((exc.code or 0, None))
            if exc.token_invalid:
                code = "token_invalid"
            raise PermanentSendError(exc.message, code=code or exc.short_code) from None
        mid = data.get("message_id")
        if not mid:
            raise TransientSendError("Meta did not return a message id")
        return SendResult(provider_message_id=str(mid))

    async def get_customer_profile(self, account: ChannelAccountRef, provider_user_id: str) -> CustomerProfile | None:
        try:
            data = await graph.get(
                f"/{provider_user_id}", token=account.access_token, fields="first_name,last_name,name"
            )
        except graph.GraphError:
            return None  # needs User Profile access; the customer keeps a placeholder name
        name = data.get("name") or " ".join(p for p in (data.get("first_name"), data.get("last_name")) if p)
        return CustomerProfile(name=name or None)
