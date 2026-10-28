"""Adapter registry. Provider packages register themselves when their phase ships (WhatsApp, Messenger)."""

from app.integrations.base import SocialChannelAdapter

_adapters: dict[str, SocialChannelAdapter] = {}


def register(adapter: SocialChannelAdapter) -> None:
    _adapters[adapter.provider] = adapter


def unregister(provider: str) -> None:
    _adapters.pop(provider, None)


def get(provider: str) -> SocialChannelAdapter | None:
    return _adapters.get(provider)


def registered() -> list[str]:
    return sorted(_adapters)
