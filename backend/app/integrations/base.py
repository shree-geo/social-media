"""Provider-neutral channel adapter contract (ARCHITECTURE.md §9).

Everything provider-specific (payload shapes, signatures, Graph API calls) lives in
``integrations/<provider>/``. Business services only see the normalized types below,
so adding Instagram or TikTok later does not touch customers, orders or payments.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Literal

MessageType = Literal[
    "text",
    "image",
    "video",
    "audio",
    "document",
    "sticker",
    "location",
    "contacts",
    "interactive",
    "reaction",
    "unsupported",
]
DeliveryStatus = Literal["sent", "delivered", "read", "failed"]


class WebhookRejected(Exception):
    """Signature/verification failure. The endpoint answers 401 and does not store the delivery."""


class SendError(Exception):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class TransientSendError(SendError):
    """Retry with backoff (timeouts, 5xx, rate limits)."""


class PermanentSendError(SendError):
    """Do not retry (window closed, recipient blocked, invalid request)."""


# --- normalized inbound events ------------------------------------------------------


@dataclass(frozen=True)
class MediaRef:
    provider_media_id: str
    mime_type: str | None = None
    filename: str | None = None
    caption: str | None = None


@dataclass(frozen=True)
class InboundMessage:
    """A customer message, or an echo of a message the business sent from the provider's own app."""

    channel_external_id: str  # phone_number_id / page_id the message arrived on
    provider_user_id: str  # wa_id / PSID of the customer
    provider_message_id: str
    timestamp: datetime
    message_type: MessageType
    text: str | None = None
    media: tuple[MediaRef, ...] = ()
    reply_to_provider_message_id: str | None = None
    profile_name: str | None = None
    phone: str | None = None  # only when the provider gives one (WhatsApp today)
    is_echo: bool = False  # sent by the business from the provider app (coexistence / Page inbox)
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MessageStatusUpdate:
    channel_external_id: str
    provider_message_id: str
    status: DeliveryStatus
    timestamp: datetime
    error_code: str | None = None
    error_message: str | None = None
    # False when receipts can refer to messages we never stored (e.g. sent before connecting).
    retry_if_unknown: bool = True


@dataclass(frozen=True)
class ReadReceipt:
    """Customer has read everything we sent up to ``watermark`` (Messenger reports reads this way)."""

    channel_external_id: str
    provider_user_id: str
    watermark: datetime


@dataclass(frozen=True)
class AccountEvent:
    """Account-level change: token revoked, quality rating, display name review, ..."""

    channel_external_id: str
    kind: str
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Unsupported:
    channel_external_id: str | None
    reason: str


NormalizedEvent = InboundMessage | MessageStatusUpdate | ReadReceipt | AccountEvent | Unsupported


# --- outbound -----------------------------------------------------------------------


@dataclass(frozen=True)
class ChannelAccountRef:
    channel_account_id: str
    external_account_id: str
    access_token: str  # decrypted just for this call; never logged


@dataclass(frozen=True)
class OutboundText:
    text: str
    reply_to_provider_message_id: str | None = None


@dataclass(frozen=True)
class SendResult:
    provider_message_id: str


@dataclass(frozen=True)
class CustomerProfile:
    name: str | None
    phone: str | None = None


class SocialChannelAdapter(ABC):
    provider: ClassVar[str]

    def verify_subscription_challenge(self, params: Mapping[str, str]) -> str | None:
        """GET handshake when registering the webhook. Return the challenge to echo, or None."""
        return None

    @abstractmethod
    def validate_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> None:
        """Raise :class:`WebhookRejected` unless the delivery is authentic. Must use constant-time compare."""

    @abstractmethod
    def parse_webhook(self, payload: Mapping[str, Any]) -> list[NormalizedEvent]:
        """Pure: no I/O. A delivery may contain several events (Meta batches them)."""

    def provider_event_id(self, payload: Mapping[str, Any]) -> str | None:
        """Delivery-level id when the provider sends one; Meta does not, so dedup is per message."""
        return None

    @abstractmethod
    async def send_text(self, account: ChannelAccountRef, to: str, message: OutboundText) -> SendResult:
        """Raise :class:`TransientSendError` or :class:`PermanentSendError` on failure."""

    async def get_customer_profile(self, account: ChannelAccountRef, provider_user_id: str) -> CustomerProfile | None:
        """Name (and phone if the provider has it) for a new customer; None when unavailable."""
        return None
