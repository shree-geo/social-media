"""Controlled test double for a channel provider (spec §53: mocks only in tests).

Payload shape (test-only, not any real provider's):
    {"events": [
        {"kind": "message", "account": "<external id>", "from": "<user id>", "id": "<msg id>",
         "ts": "<iso>", "text": "...", "name": "...", "phone": "...", "echo": false},
        {"kind": "status", "account": "...", "id": "<msg id>", "status": "delivered", "ts": "<iso>"}
    ]}
Signed with HMAC-SHA256 in ``X-Test-Signature``.
"""

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from app.integrations.base import (
    ChannelAccountRef,
    InboundMessage,
    MessageStatusUpdate,
    NormalizedEvent,
    OutboundText,
    PermanentSendError,
    SendResult,
    SocialChannelAdapter,
    TransientSendError,
    Unsupported,
    WebhookRejected,
)

SECRET = b"test-webhook-secret"


def sign(body: bytes) -> str:
    return hmac.new(SECRET, body, hashlib.sha256).hexdigest()


def body(*events: dict[str, Any]) -> bytes:
    return json.dumps({"events": list(events)}).encode()


@dataclass
class Sent:
    account: ChannelAccountRef
    to: str
    text: str


@dataclass
class FakeAdapter(SocialChannelAdapter):
    provider: ClassVar[str] = "whatsapp"
    sent: list[Sent] = field(default_factory=list)
    fail_next: list[Exception] = field(default_factory=list)
    counter: int = 0

    def verify_subscription_challenge(self, params: Mapping[str, str]) -> str | None:
        return params.get("challenge") if params.get("token") == "verify-me" else None

    def validate_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> None:
        if not hmac.compare_digest(headers.get("x-test-signature", ""), sign(raw_body)):
            raise WebhookRejected("bad signature")

    def parse_webhook(self, payload: Mapping[str, Any]) -> list[NormalizedEvent]:
        events: list[NormalizedEvent] = []
        for e in payload.get("events", []):
            ts = datetime.fromisoformat(e["ts"])
            if e["kind"] == "message":
                events.append(
                    InboundMessage(
                        channel_external_id=e["account"],
                        provider_user_id=e["from"],
                        provider_message_id=e["id"],
                        timestamp=ts,
                        message_type="text",
                        text=e.get("text"),
                        profile_name=e.get("name"),
                        phone=e.get("phone"),
                        is_echo=e.get("echo", False),
                    )
                )
            elif e["kind"] == "status":
                events.append(
                    MessageStatusUpdate(
                        channel_external_id=e["account"], provider_message_id=e["id"], status=e["status"], timestamp=ts
                    )
                )
            else:
                events.append(Unsupported(e.get("account"), "unknown kind"))
        return events

    async def send_text(self, account: ChannelAccountRef, to: str, message: OutboundText) -> SendResult:
        if self.fail_next:
            raise self.fail_next.pop(0)
        self.counter += 1
        self.sent.append(Sent(account, to, message.text))
        return SendResult(provider_message_id=f"out-{self.counter}")


__all__ = ["FakeAdapter", "PermanentSendError", "TransientSendError", "body", "sign"]
