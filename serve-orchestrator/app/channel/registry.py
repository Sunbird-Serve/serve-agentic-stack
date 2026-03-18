"""
SERVE Orchestrator - Channel Adapter Registry

Single place that maps ChannelType → ChannelAdapter instance.
Call get_adapter(channel) to retrieve the right adapter without
importing concrete adapter classes elsewhere.
"""
import logging
from app.schemas import ChannelType
from app.channel.adapters import (
    ChannelAdapter,
    WebUIAdapter,
    WhatsAppAdapter,
    APIAdapter,
    SchedulerAdapter,
    MobileAdapter,
)

logger = logging.getLogger(__name__)

_registry: dict[ChannelType, ChannelAdapter] = {
    ChannelType.WEB_UI: WebUIAdapter(),
    ChannelType.WHATSAPP: WhatsAppAdapter(),
    ChannelType.API: APIAdapter(),
    ChannelType.SCHEDULER: SchedulerAdapter(),
    ChannelType.MOBILE: MobileAdapter(),
}


def get_adapter(channel: ChannelType) -> ChannelAdapter:
    """
    Return the registered adapter for the given channel.
    Falls back to APIAdapter for any unknown channel so the pipeline
    is never blocked by a missing registration.
    """
    adapter = _registry.get(channel)
    if adapter is None:
        logger.warning(f"No adapter registered for channel '{channel}'. Falling back to APIAdapter.")
        return _registry[ChannelType.API]
    return adapter
