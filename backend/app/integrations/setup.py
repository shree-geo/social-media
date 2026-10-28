"""Register the channel adapters this deployment can use (called at API and worker start-up)."""

from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations import registry
from app.integrations.messenger.adapter import MessengerAdapter

log = get_logger(__name__)


def register_enabled_adapters() -> list[str]:
    if get_settings().meta_configured:
        registry.register(MessengerAdapter())
    else:
        log.info("meta_not_configured", detail="Messenger stays off until META_APP_ID/SECRET/GRAPH_API_VERSION are set")
    return registry.registered()
