"""
SERVE Orchestrator - Channel Adapters

Each adapter normalises raw channel input (an InteractionRequest as posted by the
channel client) into the canonical NormalizedEvent that the orchestration layer
operates on.

Adding a new channel:
  1. Create a subclass of ChannelAdapter and implement `normalize`.
  2. Register an instance in registry.py.

Design rules:
  - Adapters are pure transformers — no I/O, no side effects.
  - actor_id MUST be a stable, channel-native identifier for the human (or system)
    who sent the message so that the orchestrator can do session lookup and
    persona inference in later phases.
  - Unknown / missing values fall back to deterministic placeholders rather than
    raising, keeping the pipeline alive even with incomplete metadata.
"""
from abc import ABC, abstractmethod
from typing import Any

from app.schemas import (
    ChannelType,
    PersonaType,
    TriggerType,
    NormalizedEvent,
    InteractionRequest,
)


class ChannelAdapter(ABC):
    """Abstract base: transform raw channel input → NormalizedEvent."""

    @abstractmethod
    def normalize(self, raw_request: Any) -> NormalizedEvent:
        """Transform a raw channel request into a NormalizedEvent."""
        ...


class WebUIAdapter(ChannelAdapter):
    """
    Adapter for the React/Web UI channel.

    In SERVE, the user's email address is the canonical, stable identity across
    all channels.  actor_id priority:
      channel_metadata.email → channel_metadata.user_id → web_<session_id>

    trigger_type is always USER_MESSAGE for the web UI.
    """

    def normalize(self, request: InteractionRequest) -> NormalizedEvent:
        meta = request.channel_metadata or {}
        actor_id = (
            meta.get("email")
            or meta.get("user_id")
            or (f"web_{request.session_id}" if request.session_id else "web_anonymous")
        )
        return NormalizedEvent(
            actor_id=actor_id,
            channel=ChannelType.WEB_UI,
            trigger_type=TriggerType.USER_MESSAGE,
            payload=request.message,
            session_id=request.session_id,
            persona=request.persona,
            raw_metadata=meta,
        )


class WhatsAppAdapter(ChannelAdapter):
    """
    Adapter for the WhatsApp Business API channel.

    actor_id is the sender's E.164 phone number, which is the stable identity
    used to look up a coordinator profile.
    idempotency_key carries the WhatsApp message ID (wamid) to deduplicate
    duplicate webhook deliveries.
    """

    def normalize(self, request: InteractionRequest) -> NormalizedEvent:
        meta = request.channel_metadata or {}
        actor_id = (
            meta.get("phone_number")
            or meta.get("from")
            or meta.get("wa_id")
            or "whatsapp_unknown"
        )
        return NormalizedEvent(
            actor_id=actor_id,
            channel=ChannelType.WHATSAPP,
            trigger_type=TriggerType.USER_MESSAGE,
            payload=request.message,
            session_id=request.session_id,
            persona=request.persona,
            raw_metadata=meta,
            idempotency_key=meta.get("message_id") or meta.get("wamid"),
        )


class APIAdapter(ChannelAdapter):
    """
    Adapter for programmatic API access (integrations, test clients, bots).

    actor_id is taken from channel_metadata.actor_id / client_id so that each
    integration system gets its own stable identity.
    """

    def normalize(self, request: InteractionRequest) -> NormalizedEvent:
        meta = request.channel_metadata or {}
        actor_id = (
            meta.get("actor_id")
            or meta.get("client_id")
            or "api_client"
        )
        return NormalizedEvent(
            actor_id=actor_id,
            channel=ChannelType.API,
            trigger_type=TriggerType.USER_MESSAGE,
            payload=request.message,
            session_id=request.session_id,
            persona=request.persona,
            raw_metadata=meta,
        )


class SchedulerAdapter(ChannelAdapter):
    """
    Adapter for system-triggered / scheduled events (cron jobs, reminders,
    follow-up nudges).

    actor_id is the scheduler job ID. trigger_type is SCHEDULED by default;
    callers may override by embedding trigger_type in channel_metadata.
    Persona defaults to SYSTEM when not explicitly set.
    """

    def normalize(self, request: InteractionRequest) -> NormalizedEvent:
        meta = request.channel_metadata or {}
        actor_id = (
            meta.get("scheduled_job_id")
            or meta.get("trigger_id")
            or "scheduler"
        )
        raw_trigger = meta.get("trigger_type", TriggerType.SCHEDULED.value)
        try:
            trigger_type = TriggerType(raw_trigger)
        except ValueError:
            trigger_type = TriggerType.SCHEDULED

        return NormalizedEvent(
            actor_id=actor_id,
            channel=ChannelType.SCHEDULER,
            trigger_type=trigger_type,
            payload=request.message,
            session_id=request.session_id,
            persona=request.persona or PersonaType.SYSTEM,
            raw_metadata=meta,
        )


class MobileAdapter(ChannelAdapter):
    """
    Adapter for the mobile app channel.

    In SERVE, the user's email address is the canonical, stable identity across
    all channels.  Using email (rather than device_id) ensures that a volunteer
    who switches phones or reinstalls the app is still recognised as the same
    person.  actor_id priority:
      channel_metadata.email → channel_metadata.user_id → mobile_<session_id>

    Device-scoped identifiers (device_id) are intentionally excluded because
    they represent the hardware, not the authenticated user.
    """

    def normalize(self, request: InteractionRequest) -> NormalizedEvent:
        meta = request.channel_metadata or {}
        actor_id = (
            meta.get("email")
            or meta.get("user_id")
            or (f"mobile_{request.session_id}" if request.session_id else "mobile_anonymous")
        )
        return NormalizedEvent(
            actor_id=actor_id,
            channel=ChannelType.MOBILE,
            trigger_type=TriggerType.USER_MESSAGE,
            payload=request.message,
            session_id=request.session_id,
            persona=request.persona,
            raw_metadata=meta,
        )
