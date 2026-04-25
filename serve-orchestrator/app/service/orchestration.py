"""
SERVE Orchestrator Service - Orchestration Logic
Central coordination layer for SERVE AI with clean abstractions.

Architecture:
  Channel Input (InteractionRequest)
      ↓  [Channel Adapter layer — app/channel/]
  NormalizedEvent  (actor_id, channel, trigger_type, payload, …)
      ↓  [process_event — this module]
  Session resolve/create  →  AgentRouter  →  Agent  →  WorkflowValidator
      ↓
  InteractionResponse

Public interface:
  process_interaction(request)  — thin wrapper that normalises then calls process_event
  process_event(event)          — main orchestration logic; testable directly
"""
from typing import Optional, Tuple, Dict
from uuid import UUID, uuid4
from datetime import datetime, timedelta
import json


def _safe_uuid(value) -> Optional[UUID]:
    """Convert a string to UUID safely. Returns None if invalid."""
    if not value:
        return None
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return None
import logging

from app.schemas import (
    InteractionRequest, InteractionResponse, SessionState,
    AgentTurnRequest, AgentTurnResponse,
    PersonaType, WorkflowType, AgentType, SessionStatus, OnboardingState,
    NormalizedEvent, TriggerType, IntentType, IntentResult, PersonaResolutionResult,
)
from app.schemas.contracts import (
    RoutingDecision, TransitionValidation, SessionContext,
    OrchestrationEvent, OrchestrationEventType
)
from app.clients import domain_client
from app.channel.registry import get_adapter
from app.service.agent_router import agent_router
from app.service.intent_resolver import intent_resolver
from app.service.persona_resolver import persona_resolver
from app.service.workflow_validator import workflow_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Idempotency cache — prevents duplicate processing of WhatsApp (or other
# channel) messages that arrive more than once.  Keyed on the idempotency_key
# set by the channel adapter.  A simple in-memory dict is sufficient for a
# single-instance deployment; swap for Redis in Phase 6 for multi-replica.
# ---------------------------------------------------------------------------
_seen_keys: Dict[str, datetime] = {}
_DEDUP_TTL = timedelta(minutes=5)


def _is_duplicate_event(key: Optional[str]) -> bool:
    """Return True and record the key if it has been seen within the TTL window."""
    if not key:
        return False

    now = datetime.utcnow()
    # Bounded cleanup: evict expired entries on every check
    expired = [k for k, t in _seen_keys.items() if (now - t) > _DEDUP_TTL]
    for k in expired:
        del _seen_keys[k]

    if key in _seen_keys:
        return True

    _seen_keys[key] = now
    return False


def determine_workflow(persona: PersonaType) -> WorkflowType:
    """
    Determine the appropriate workflow based on persona type.
    
    This mapping defines which workflow handles each persona:
    - New volunteers → Onboarding workflow
    - Returning volunteers → Engagement workflow (future)
    - Need coordinators → Need coordination workflow (future)
    """
    persona_workflow_map = {
        PersonaType.NEW_VOLUNTEER: WorkflowType.NEW_VOLUNTEER_ONBOARDING,
        PersonaType.RETURNING_VOLUNTEER: WorkflowType.RETURNING_VOLUNTEER,
        PersonaType.RECOMMENDED_VOLUNTEER: WorkflowType.RECOMMENDED_VOLUNTEER,
        PersonaType.NEED_COORDINATOR: WorkflowType.NEED_COORDINATION,
    }
    return persona_workflow_map.get(persona, WorkflowType.NEW_VOLUNTEER_ONBOARDING)


def determine_initial_agent(workflow: WorkflowType) -> AgentType:
    """
    Determine the initial agent for a workflow.
    
    Each workflow starts with a specific agent:
    - Onboarding workflow → Onboarding agent
    - Returning volunteer → Engagement agent (future)
    - Need coordination → Need agent (future)
    """
    workflow_agent_map = {
        WorkflowType.NEW_VOLUNTEER_ONBOARDING: AgentType.ONBOARDING,
        WorkflowType.RETURNING_VOLUNTEER: AgentType.ENGAGEMENT,
        WorkflowType.RECOMMENDED_VOLUNTEER: AgentType.ENGAGEMENT,
        WorkflowType.NEED_COORDINATION: AgentType.NEED,
    }
    return workflow_agent_map.get(workflow, AgentType.ONBOARDING)


class OrchestrationService:
    """
    Central orchestration service implementing the coordination pattern.
    
    Responsibilities:
    1. Session lifecycle management (create, resume, complete)
    2. Request routing to appropriate agents
    3. State transition validation and persistence
    4. Structured logging of all orchestration events
    """
    
    async def process_interaction(self, request: InteractionRequest) -> InteractionResponse:
        """
        Public entry point for all channel clients.

        Selects the right ChannelAdapter for `request.channel`, normalises the
        raw InteractionRequest into a NormalizedEvent, then delegates to
        process_event for all orchestration logic.
        """
        adapter = get_adapter(request.channel)
        event = adapter.normalize(request)
        return await self.process_event(event)

    async def process_event(self, event: NormalizedEvent) -> InteractionResponse:
        """
        Core orchestration loop operating on a canonical NormalizedEvent.

        Flow:
          1. Resume or create session
          2. Save incoming user message
          3. Route to appropriate agent
          4. Invoke agent
          5. Validate & persist state transition
          6. Save agent reply
          7. Emit handoff (if any)
          8. Build and return InteractionResponse

        Never raises — all failures produce a graceful InteractionResponse so every
        channel always receives a usable reply rather than an HTTP 5xx.
        """
        # ── Idempotency guard — reject duplicate webhook deliveries early so we
        #    never double-charge the LLM or produce double replies to the user.
        if _is_duplicate_event(event.idempotency_key):
            logger.warning(
                f"Duplicate event suppressed: idempotency_key={event.idempotency_key!r} "
                f"actor={event.actor_id!r}"
            )
            return InteractionResponse(
                session_id=event.session_id,
                assistant_message="",   # empty — channel adapter should NOT forward to user
                active_agent=AgentType.ONBOARDING,
                workflow=WorkflowType.NEW_VOLUNTEER_ONBOARDING,
                state="",
                is_complete=False,
                is_duplicate=True,
                debug_info={"duplicate": True, "idempotency_key": event.idempotency_key},
            )

        start_time = datetime.utcnow()
        session_context = None
        conversation = []

        # Step 1: Resolve persona — only needed for new sessions.
        # Resumed sessions restore persona from persistent storage in _resume_session.
        persona_result: Optional[PersonaResolutionResult] = None
        if not event.session_id:
            persona_result = await persona_resolver.resolve(event)
            # Stamp the resolved persona back onto the event so all downstream
            # code (session creation, fallback response) sees a consistent value.
            event = event.model_copy(update={'persona': persona_result.persona})

        # Step 2: Resolve or create session
        if event.session_id:
            session_context, conversation = await self._resume_session(event)

        if not session_context:
            session_context = await self._create_session(event)

        if not session_context:
            logger.error(
                f"Session creation failed for actor={event.actor_id!r} "
                f"channel={event.channel.value} — MCP server may be unavailable"
            )
            return self._fallback_response(
                session_id=event.session_id,
                message="I'm having trouble connecting right now. Please try again in a moment.",
                persona=event.persona,
            )

        # Log session context established (Step 3)
        self._log_event(
            session_id=session_context.session_id,
            event_type=OrchestrationEventType.SESSION_RESUMED if event.session_id
                       else OrchestrationEventType.SESSION_CREATED,
            workflow=session_context.workflow,
            stage=session_context.current_stage,
            details={
                'channel': session_context.channel,
                'persona': session_context.persona,
                'actor_id': event.actor_id,
                'trigger_type': event.trigger_type.value,
            }
        )

        # Log persona resolution for new sessions now that we have a session_id
        if persona_result is not None:
            self._log_event(
                session_id=session_context.session_id,
                event_type=OrchestrationEventType.PERSONA_RESOLVED,
                details={
                    'persona': persona_result.persona.value,
                    'confidence': persona_result.confidence,
                    'source': persona_result.source,
                    'actor_id': event.actor_id,
                    **{k: v for k, v in persona_result.metadata.items()
                       if k != 'error'},
                }
            )

        # Step 2: Resolve intent — before saving message so terminal intents
        #         (pause, escalate, restart) can short-circuit without wasting
        #         storage writes.
        intent_result = intent_resolver.resolve(event, session_context)
        self._log_event(
            session_id=session_context.session_id,
            event_type=OrchestrationEventType.INTENT_RESOLVED,
            details={
                'intent': intent_result.intent.value,
                'confidence': intent_result.confidence,
                'signal': intent_result.metadata.get('signal'),
                'matched': intent_result.metadata.get('matched'),
            }
        )

        # Step 2a: Short-circuit on terminal intents handled at orchestrator level
        if intent_result.intent == IntentType.PAUSE_SESSION:
            return await self._handle_pause(session_context, event, intent_result)

        if intent_result.intent == IntentType.ESCALATE:
            return await self._handle_escalation(session_context, event, intent_result)

        if intent_result.intent == IntentType.RESTART:
            return await self._handle_restart(event, intent_result)

        # Step 3: Save user message (non-critical — log warning on failure but continue)
        save_result = await domain_client.save_message(
            session_id=session_context.session_id,
            role="user",
            content=event.payload,
            agent=session_context.active_agent
        )
        if save_result.get("status") == "error":
            logger.warning(
                f"[{session_context.session_id}] Failed to save user message: "
                f"{save_result.get('error')}"
            )

        # Log message received
        self._log_event(
            session_id=session_context.session_id,
            event_type=OrchestrationEventType.MESSAGE_RECEIVED,
            details={
                'message_length': len(event.payload),
                'trigger_type': event.trigger_type.value,
                'intent': intent_result.intent.value,
            }
        )

        # Step 4: Make routing decision (intent-aware)
        session_state = SessionState(
            id=session_context.session_id,
            channel=session_context.channel,
            persona=session_context.persona,
            workflow=session_context.workflow,
            active_agent=session_context.active_agent,
            status=session_context.status,
            stage=session_context.current_stage,
            sub_state=session_context.sub_state,
            context_summary=session_context.context_summary,
            volunteer_id=_safe_uuid(session_context.volunteer_id),
            volunteer_name=session_context.volunteer_name,
            volunteer_phone=session_context.volunteer_phone,
            # Forward live channel metadata (e.g. phone_number from Web UI pre-screen)
            channel_metadata=event.raw_metadata if event.raw_metadata else None,
            created_at=session_context.created_at.isoformat() if session_context.created_at else None,
            updated_at=session_context.updated_at.isoformat() if session_context.updated_at else None
        )

        routing_decision = agent_router.make_routing_decision(
            session_context=session_state,
            user_message=event.payload,
            intent=intent_result,
        )

        agent_router.log_routing_event(
            session_id=session_context.session_id,
            decision=routing_decision
        )

        # Step 5: Invoke agent, passing the resolved intent as a hint and live channel metadata
        agent_request = AgentTurnRequest(
            session_id=session_context.session_id,
            session_state=session_state,
            user_message=event.payload,
            conversation_history=conversation,
            intent_hint=intent_result.intent.value,
            channel_metadata=event.raw_metadata if event.raw_metadata else None,
        )

        self._log_event(
            session_id=session_context.session_id,
            event_type=OrchestrationEventType.AGENT_INVOKED,
            agent=routing_decision.target_agent,
            details={
                'confidence': routing_decision.confidence,
                'intent': intent_result.intent.value,
            }
        )

        agent_response = await agent_router.invoke_agent(routing_decision, agent_request)

        agent_duration = (datetime.utcnow() - start_time).total_seconds() * 1000
        self._log_event(
            session_id=session_context.session_id,
            event_type=OrchestrationEventType.AGENT_RESPONDED,
            agent=agent_response.active_agent.value,
            stage=agent_response.state,
            duration_ms=agent_duration,
            details={
                'response_length': len(agent_response.assistant_message),
                'completion_status': agent_response.completion_status
            }
        )

        # Step 6: Validate and apply state transition
        # (was Step 5 before intent resolution was added)
        if agent_response.state != session_context.current_stage:
            validation = workflow_validator.validate_transition(
                workflow_id=session_context.workflow,
                from_state=session_context.current_stage,
                to_state=agent_response.state,
                confirmed_fields=agent_response.confirmed_fields,
                session_id=session_context.session_id
            )

            workflow_validator.log_validation_event(
                session_id=session_context.session_id,
                validation=validation,
                workflow_id=session_context.workflow
            )

            if validation.is_valid:
                advance_result = await domain_client.advance_state(
                    session_id=session_context.session_id,
                    new_state=agent_response.state,
                    sub_state=agent_response.sub_state
                )
                if advance_result.get("status") == "error":
                    logger.warning(
                        f"[{session_context.session_id}] State advance "
                        f"({session_context.current_stage} → {agent_response.state}) "
                        f"failed: {advance_result.get('error')}"
                    )
            else:
                logger.warning(
                    f"[{session_context.session_id}] Transition blocked "
                    f"({session_context.current_stage} → {agent_response.state}): "
                    f"{validation.reason}"
                )

        # Step 6: Save assistant message (non-critical — log warning on failure)
        save_result = await domain_client.save_message(
            session_id=session_context.session_id,
            role="assistant",
            content=agent_response.assistant_message,
            agent=agent_response.active_agent.value
        )
        if save_result.get("status") == "error":
            logger.warning(
                f"[{session_context.session_id}] Failed to save assistant message: "
                f"{save_result.get('error')}"
            )

        # Step 7: Handle handoff if present
        if agent_response.handoff_event:
            to_agent_value = agent_response.handoff_event.to_agent.value

            handoff_result = await domain_client.emit_handoff_event(
                session_id=session_context.session_id,
                from_agent=agent_response.handoff_event.from_agent.value,
                to_agent=to_agent_value,
                handoff_type=agent_response.handoff_event.handoff_type.value,
                payload=agent_response.handoff_event.payload,
                reason=agent_response.handoff_event.reason
            )
            if handoff_result.get("status") == "error":
                logger.warning(
                    f"[{session_context.session_id}] Handoff event emit failed: "
                    f"{handoff_result.get('error')}"
                )

            # Critical: persist the new active_agent and the target agent's
            # handoff sub_state so the payload survives any failure in the
            # auto-invoke path.
            handoff_sub_state_str = agent_response.sub_state
            handoff_payload = agent_response.handoff_event.payload if agent_response.handoff_event else {}
            target_sub_state = handoff_payload.get("target_sub_state") if isinstance(handoff_payload, dict) else None

            if to_agent_value == "fulfillment" and handoff_payload:
                handoff_sub_state_str = json.dumps({
                    "handoff": handoff_payload,
                    "nominated_need_id": None,
                    "human_review_reason": None,
                })
            elif target_sub_state is not None:
                handoff_sub_state_str = (
                    target_sub_state
                    if isinstance(target_sub_state, str)
                    else json.dumps(target_sub_state)
                )
            elif handoff_payload and handoff_sub_state_str is None:
                handoff_sub_state_str = json.dumps({"handoff": handoff_payload})

            handoff_advance = await domain_client.advance_state(
                session_id=session_context.session_id,
                new_state=agent_response.state,
                active_agent=to_agent_value,
                sub_state=handoff_sub_state_str,
            )
            if handoff_advance.get("status") == "error":
                logger.warning(
                    f"[{session_context.session_id}] Failed to persist active_agent "
                    f"after handoff to {to_agent_value!r}: {handoff_advance.get('error')}"
                )
            else:
                logger.info(
                    f"[{session_context.session_id}] active_agent updated → {to_agent_value!r}, "
                    f"handoff sub_state persisted"
                )

            self._log_event(
                session_id=session_context.session_id,
                event_type=OrchestrationEventType.HANDOFF_INITIATED,
                agent=to_agent_value,
                details={
                    'from_agent': agent_response.handoff_event.from_agent.value,
                    'to_agent': to_agent_value,
                    'reason': agent_response.handoff_event.reason,
                }
            )

            # ── Auto-invoke the target agent immediately so the volunteer
            #    doesn't have to send another message to trigger it.
            #    We update session_context to reflect the new active_agent,
            #    then invoke that target agent with a synthetic trigger.
            try:
                session_context.active_agent = to_agent_value
                session_context.current_stage = agent_response.state

                auto_session_state = SessionState(
                    id=session_context.session_id,
                    channel=session_context.channel,
                    persona=session_context.persona,
                    workflow=session_context.workflow,
                    active_agent=to_agent_value,
                    status=session_context.status,
                    stage=agent_response.state,
                    sub_state=handoff_sub_state_str,
                    volunteer_id=_safe_uuid(session_context.volunteer_id),
                    volunteer_name=session_context.volunteer_name,
                    volunteer_phone=session_context.volunteer_phone,
                    channel_metadata=event.raw_metadata if event.raw_metadata else None,
                )

                auto_routing = agent_router.make_routing_decision(
                    session_context=auto_session_state,
                    user_message="__handoff__",
                    intent=intent_result,
                )

                auto_request = AgentTurnRequest(
                    session_id=session_context.session_id,
                    session_state=auto_session_state,
                    user_message="__handoff__",
                    conversation_history=[],  # start fresh — engagement history confuses fulfillment
                    intent_hint="continue_workflow",
                    channel_metadata=event.raw_metadata if event.raw_metadata else None,
                )

                auto_response = await agent_router.invoke_agent(auto_routing, auto_request)

                if auto_response.assistant_message:
                    # Hardcoded transition line based on handoff pair
                    from_agent = agent_response.handoff_event.from_agent.value
                    transition_lines = {
                        ("onboarding", "selection"): (
                            "Registration complete!\n\n"
                            "Step 2/4 → Getting to Know You\n"
                            "✅ Orientation & Registration  →  🔵 Getting to Know You  →  ○ Schedule Preferences  →  ○ Teaching Assignment"
                        ),
                        ("selection", "engagement"): (
                            "Step 3/4 → Schedule Preferences\n"
                            "✅ Orientation & Registration  →  ✅ Getting to Know You  →  🔵 Schedule Preferences  →  ○ Teaching Assignment"
                        ),
                        ("engagement", "fulfillment"): (
                            "Step 4/4 → Teaching Assignment\n"
                            "✅ Orientation & Registration  →  ✅ Getting to Know You  →  ✅ Schedule Preferences  →  🔵 Teaching Assignment"
                        ),
                        ("recommended_handler", "fulfillment"): (
                            "Step 4/4 → Teaching Assignment\n"
                            "✅ Orientation & Registration  →  ✅ Getting to Know You  →  ✅ Schedule Preferences  →  🔵 Teaching Assignment"
                        ),
                    }
                    transition = transition_lines.get(
                        (from_agent, to_agent_value),
                        None
                    )
                    agent_response = auto_response
                    if transition:
                        agent_response.preliminary_message = transition
                    logger.info(
                        f"[{session_context.session_id}] Auto-invoked {to_agent_value!r} "
                        f"after handoff — response length={len(auto_response.assistant_message)}, "
                        f"auto_continue={getattr(auto_response, 'auto_continue', False)}"
                    )
            except Exception as e:
                logger.warning(
                    f"[{session_context.session_id}] Auto-invoke of {to_agent_value!r} failed: {e} "
                    f"— returning engagement closing message"
                )

        # Step 8: Calculate progress and build response
        # For need coordination, prefer the agent's field-level completion percentage
        # (accurate during drafting) over the coarse stage-based one.
        stage_progress = workflow_validator.get_completion_percentage(
            workflow_id=session_context.workflow,
            current_stage=agent_response.state
        )
        agent_pct = agent_response.confirmed_fields.get("completion_percentage") if agent_response.confirmed_fields else None
        progress_percent = (
            agent_pct
            if agent_pct is not None and session_context.workflow == "need_coordination"
            else stage_progress
        )

        is_complete = workflow_validator.is_terminal_stage(
            workflow_id=session_context.workflow,
            stage=agent_response.state
        )

        total_duration = (datetime.utcnow() - start_time).total_seconds() * 1000

        return InteractionResponse(
            session_id=session_context.session_id,
            assistant_message=agent_response.assistant_message,
            preliminary_message=getattr(agent_response, 'preliminary_message', None),
            auto_continue=agent_response.auto_continue,
            active_agent=agent_response.active_agent,
            workflow=agent_response.workflow,
            state=agent_response.state,
            sub_state=agent_response.sub_state,
            status=SessionStatus.COMPLETED if is_complete else SessionStatus.ACTIVE,
            is_complete=is_complete,
            journey_progress={
                "current_state": agent_response.state,
                "progress_percent": progress_percent,
                "confirmed_fields": agent_response.confirmed_fields,
                "missing_fields": agent_response.missing_fields,
            },
            debug_info={
                "persona": {
                    "value": persona_result.persona.value if persona_result else session_context.persona,
                    "confidence": persona_result.confidence if persona_result else None,
                    "source": persona_result.source if persona_result else "resumed_from_session",
                },
                "intent": {
                    "type": intent_result.intent.value,
                    "confidence": intent_result.confidence,
                    "signal": intent_result.metadata.get("signal"),
                },
                "routing": {
                    "target_agent": routing_decision.target_agent,
                    "confidence": routing_decision.confidence,
                    "reason": routing_decision.reason
                },
                "timing_ms": total_duration,
                "telemetry_events": [e.model_dump(mode="json") for e in agent_response.telemetry_events]
            }
        )

    async def _resume_session(self, event: NormalizedEvent) -> Tuple[Optional[SessionContext], list]:
        """
        Resume an existing session by its ID.

        Returns (SessionContext, conversation_history) on success, (None, []) on any failure.
        """
        resume_result = await domain_client.resume_context(event.session_id)

        if resume_result.get("status") != "success":
            return None, []

        data = resume_result.get("data", {})
        session_data = data.get("session")

        if not session_data:
            return None, []

        session_context = SessionContext(
            session_id=UUID(session_data["id"]),
            channel=event.channel.value,
            persona=(
                event.persona.value if event.persona
                else session_data.get("persona", "new_volunteer")
            ),
            workflow=session_data["workflow"],
            active_agent=session_data["active_agent"],
            status=session_data["status"],
            current_stage=session_data["stage"],
            sub_state=session_data.get("sub_state"),
            context_summary=session_data.get("context_summary"),
            volunteer_profile=data.get("volunteer_profile"),
            volunteer_id=session_data.get("volunteer_id"),
            volunteer_name=(
                session_data.get("volunteer_name")
                or (session_data.get("channel_metadata") or {}).get("volunteer_name")
            ),
            created_at=datetime.fromisoformat(session_data["created_at"]) if session_data.get("created_at") else None,
            updated_at=datetime.fromisoformat(session_data["updated_at"]) if session_data.get("updated_at") else None
        )

        return session_context, data.get("conversation_history", [])

    async def _create_session(self, event: NormalizedEvent) -> Optional[SessionContext]:
        """
        Create a new session via the MCP server.

        Passes actor_id and trigger_type in channel_metadata so the MCP server
        can persist them against the session record for future persona resolution.
        Returns None on failure so the caller can issue a graceful fallback response.
        """
        persona = event.persona or PersonaType.NEW_VOLUNTEER
        workflow = determine_workflow(persona)
        initial_agent = determine_initial_agent(workflow)

        # Merge actor_id + trigger_type into channel_metadata
        channel_metadata = {
            "actor_id": event.actor_id,
            "trigger_type": event.trigger_type.value,
            **event.raw_metadata,
        }

        # Extract volunteer_phone / volunteer_name if passed via channel_metadata (e.g. returning volunteer UI)
        volunteer_phone = event.raw_metadata.get("volunteer_phone")
        volunteer_name = event.raw_metadata.get("volunteer_name")

        start_result = await domain_client.start_session(
            channel=event.channel.value,
            persona=persona.value,
            channel_metadata=channel_metadata,
            volunteer_phone=volunteer_phone,
        )

        if start_result.get("status") != "success":
            logger.error(
                f"MCP start_session failed for actor={event.actor_id!r}: "
                f"status={start_result.get('status')!r} error={start_result.get('error')!r}"
            )
            return None

        session_id = UUID(start_result["data"]["session_id"])
        now = datetime.utcnow()

        return SessionContext(
            session_id=session_id,
            channel=event.channel.value,
            persona=persona.value,
            workflow=workflow.value,
            active_agent=initial_agent.value,
            status=SessionStatus.ACTIVE.value,
            current_stage=start_result["data"].get("stage", OnboardingState.WELCOME.value),
            volunteer_id=None,
            volunteer_name=volunteer_name,
            volunteer_phone=volunteer_phone,
            created_at=now,
            updated_at=now
        )

    # ------------------------------------------------------------------ #
    #  Terminal intent handlers — short-circuit without invoking agents  #
    # ------------------------------------------------------------------ #

    async def _handle_pause(
        self,
        session_context: SessionContext,
        event: NormalizedEvent,
        intent_result: IntentResult,
    ) -> InteractionResponse:
        """
        Pause the session and return a farewell response.
        Advances the session state to 'paused' so a future resume restores context.
        """
        await domain_client.save_message(
            session_id=session_context.session_id,
            role="user",
            content=event.payload,
            agent=session_context.active_agent,
        )
        await domain_client.advance_state(
            session_id=session_context.session_id,
            new_state="paused",
        )
        msg = (
            intent_result.suggested_response
            or "No problem! I've saved your progress. Come back anytime and we'll pick up right where you left off."
        )
        await domain_client.save_message(
            session_id=session_context.session_id,
            role="assistant",
            content=msg,
            agent=session_context.active_agent,
        )
        self._log_event(
            session_id=session_context.session_id,
            event_type=OrchestrationEventType.STATE_TRANSITION,
            stage="paused",
            details={"intent": "pause_session", "from_stage": session_context.current_stage},
        )
        return InteractionResponse(
            session_id=session_context.session_id,
            assistant_message=msg,
            active_agent=AgentType(session_context.active_agent),
            workflow=WorkflowType(session_context.workflow),
            state="paused",
            status=SessionStatus.PAUSED,
        )

    async def _handle_escalation(
        self,
        session_context: SessionContext,
        event: NormalizedEvent,
        intent_result: IntentResult,
    ) -> InteractionResponse:
        """
        Mark session for human review and return a handoff acknowledgement.
        Uses 'paused' state + 'human_review' sub_state so both onboarding and
        need workflows are handled gracefully without requiring new workflow states.
        """
        await domain_client.save_message(
            session_id=session_context.session_id,
            role="user",
            content=event.payload,
            agent=session_context.active_agent,
        )
        await domain_client.advance_state(
            session_id=session_context.session_id,
            new_state="paused",
            sub_state="human_review",
        )
        msg = (
            intent_result.suggested_response
            or (
                "I understand you'd like to speak with a person. "
                "I've flagged your session for our support team and someone will be in touch shortly. "
                "Your progress has been saved."
            )
        )
        await domain_client.save_message(
            session_id=session_context.session_id,
            role="assistant",
            content=msg,
            agent=session_context.active_agent,
        )
        self._log_event(
            session_id=session_context.session_id,
            event_type=OrchestrationEventType.HANDOFF_INITIATED,
            details={"intent": "escalate", "sub_state": "human_review"},
        )
        return InteractionResponse(
            session_id=session_context.session_id,
            assistant_message=msg,
            active_agent=AgentType(session_context.active_agent),
            workflow=WorkflowType(session_context.workflow),
            state="paused",
            sub_state="human_review",
            status=SessionStatus.ESCALATED,
        )

    async def _handle_restart(
        self,
        event: NormalizedEvent,
        intent_result: IntentResult,
    ) -> InteractionResponse:
        """
        Discard session_id and create a completely fresh session for the actor.
        The old session remains in Postgres for audit purposes.
        """
        fresh_event = NormalizedEvent(
            actor_id=event.actor_id,
            channel=event.channel,
            trigger_type=event.trigger_type,
            payload=event.payload,
            session_id=None,
            persona=event.persona,
            raw_metadata={**event.raw_metadata, "restart": True},
        )
        new_context = await self._create_session(fresh_event)
        if not new_context:
            return self._fallback_response(
                session_id=None,
                message="I'm having trouble starting a new session. Please try again in a moment.",
                persona=event.persona,
            )
        msg = (
            intent_result.suggested_response
            or (
                "Of course! Let's start fresh. "
                "Welcome — I'm here to help you join eVidyaloka as a volunteer. "
                "What would you like to do today?"
            )
        )
        await domain_client.save_message(
            session_id=new_context.session_id,
            role="assistant",
            content=msg,
            agent=new_context.active_agent,
        )
        self._log_event(
            session_id=new_context.session_id,
            event_type=OrchestrationEventType.SESSION_CREATED,
            workflow=new_context.workflow,
            stage=new_context.current_stage,
            details={"intent": "restart", "actor_id": event.actor_id},
        )
        return InteractionResponse(
            session_id=new_context.session_id,
            assistant_message=msg,
            active_agent=AgentType(new_context.active_agent),
            workflow=WorkflowType(new_context.workflow),
            state=new_context.current_stage,
            status=SessionStatus.ACTIVE,
        )

    def _fallback_response(
        self,
        session_id: Optional[UUID],
        message: str,
        persona: Optional[PersonaType] = None,
    ) -> InteractionResponse:
        """
        Construct a safe fallback InteractionResponse when the orchestrator cannot
        complete the normal flow (e.g. MCP server is down).
        """
        _persona = persona or PersonaType.NEW_VOLUNTEER
        _workflow = determine_workflow(_persona)
        _agent = determine_initial_agent(_workflow)
        return InteractionResponse(
            session_id=session_id or uuid4(),
            assistant_message=message,
            active_agent=_agent,
            workflow=_workflow,
            state=OnboardingState.WELCOME.value,
            status=SessionStatus.ACTIVE,
        )
    
    def _log_event(
        self,
        session_id: UUID,
        event_type: OrchestrationEventType,
        agent: str = None,
        workflow: str = None,
        stage: str = None,
        duration_ms: float = None,
        details: dict = None
    ):
        """
        Create and log an orchestration event.
        """
        event = OrchestrationEvent(
            event_type=event_type,
            session_id=session_id,
            agent=agent,
            workflow=workflow,
            stage=stage,
            duration_ms=duration_ms,
            details=details or {}
        )
        
        logger.info(f"Orchestration: {event.to_log_dict()}")
    
    async def get_session(self, session_id: UUID) -> dict:
        """Get session state."""
        return await domain_client.get_session(session_id)
    
    async def list_sessions(self, status: str = None, limit: int = 50) -> dict:
        """List all sessions."""
        return await domain_client.list_sessions(status, limit)


# Singleton instance
orchestration_service = OrchestrationService()
