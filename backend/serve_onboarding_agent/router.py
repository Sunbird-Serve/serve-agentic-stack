"""
SERVE AI - Onboarding Agent Service
Autonomous agent for volunteer onboarding
"""
from fastapi import APIRouter
from datetime import datetime
from typing import List, Dict, Any
import httpx
import os

from shared.contracts import (
    AgentTurnRequest, AgentTurnResponse, HealthResponse,
    TelemetryEvent, HandoffEvent
)
from shared.enums import (
    AgentType, WorkflowType, OnboardingState, EventType, HandoffType
)
from .llm_adapter import llm_adapter

onboarding_router = APIRouter(prefix="/agents/onboarding", tags=["Onboarding Agent"])

MCP_BASE_URL = os.environ.get("MCP_SERVICE_URL", "http://localhost:8001/api/mcp")


# State machine configuration
STATE_TRANSITIONS = {
    OnboardingState.INIT.value: [OnboardingState.INTENT_DISCOVERY.value],
    OnboardingState.INTENT_DISCOVERY.value: [OnboardingState.PURPOSE_ORIENTATION.value, OnboardingState.PAUSED.value],
    OnboardingState.PURPOSE_ORIENTATION.value: [OnboardingState.ELIGIBILITY_CONFIRMATION.value, OnboardingState.PAUSED.value],
    OnboardingState.ELIGIBILITY_CONFIRMATION.value: [OnboardingState.CAPABILITY_DISCOVERY.value, OnboardingState.PAUSED.value],
    OnboardingState.CAPABILITY_DISCOVERY.value: [OnboardingState.PROFILE_CONFIRMATION.value, OnboardingState.PAUSED.value],
    OnboardingState.PROFILE_CONFIRMATION.value: [OnboardingState.ONBOARDING_COMPLETE.value, OnboardingState.CAPABILITY_DISCOVERY.value, OnboardingState.PAUSED.value],
    OnboardingState.ONBOARDING_COMPLETE.value: [],
    OnboardingState.PAUSED.value: [s.value for s in OnboardingState if s != OnboardingState.PAUSED],
}


# System prompts for each state
STATE_PROMPTS = {
    OnboardingState.INIT.value: """You are SERVE AI, a friendly and professional volunteer onboarding assistant for the SERVE volunteer management platform. 

Your role is to guide new volunteers through the onboarding process. In this initial stage, warmly greet the user and introduce yourself. Ask them what brings them to volunteer and what they hope to achieve.

Keep your response friendly, concise (2-3 sentences), and end with a question to understand their motivation.""",

    OnboardingState.INTENT_DISCOVERY.value: """You are SERVE AI, helping with volunteer onboarding. You're in the Intent Discovery phase.

Your goal is to understand:
- Why the volunteer wants to participate
- What kind of impact they hope to make
- Any specific causes or areas they're passionate about

Based on their response, acknowledge their motivation and gently guide them to share more about their interests. Keep responses conversational and supportive.""",

    OnboardingState.PURPOSE_ORIENTATION.value: """You are SERVE AI in the Purpose Orientation phase.

Help the volunteer understand:
- How SERVE connects volunteers with meaningful opportunities
- The types of volunteer work available
- How their skills and interests can make a difference

Share briefly about the program and ask what types of activities interest them most.""",

    OnboardingState.ELIGIBILITY_CONFIRMATION.value: """You are SERVE AI in the Eligibility Confirmation phase.

Gather essential information to confirm eligibility:
- Basic contact information (name, email)
- Location/availability
- Any relevant experience

Be warm and explain why this information helps match them with opportunities. Ask for one piece of information at a time.""",

    OnboardingState.CAPABILITY_DISCOVERY.value: """You are SERVE AI in the Capability Discovery phase.

Explore the volunteer's:
- Skills and expertise
- Available time commitment
- Preferred types of volunteer work
- Any certifications or special training

Help them articulate their strengths and match them to volunteer opportunities. Be encouraging about the skills they share.""",

    OnboardingState.PROFILE_CONFIRMATION.value: """You are SERVE AI in the Profile Confirmation phase.

Summarize what you've learned about the volunteer and confirm the details are correct. Present their profile information and ask if anything needs to be updated.

Be clear, organized, and reassuring that their information will be used to find the best volunteer matches.""",

    OnboardingState.ONBOARDING_COMPLETE.value: """You are SERVE AI completing the onboarding process.

Congratulate the volunteer on completing onboarding! Let them know:
- Their profile is now complete
- What happens next (matching with opportunities)
- How they can get in touch if they have questions

Be warm, celebratory, and set positive expectations for their volunteer journey.""",
}


async def call_mcp_capability(endpoint: str, payload: dict) -> dict:
    """Call MCP capability endpoint"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{MCP_BASE_URL}/capabilities/onboarding/{endpoint}",
                json=payload,
                timeout=30.0
            )
            return response.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}


def determine_next_state(current_state: str, user_message: str, missing_fields: List[str]) -> str:
    """
    Determine the next state based on current state and user input.
    Simple heuristic for MVP - can be enhanced with ML later.
    """
    # Check for pause/stop signals
    pause_signals = ["pause", "stop", "later", "bye", "quit", "exit"]
    if any(signal in user_message.lower() for signal in pause_signals):
        return OnboardingState.PAUSED.value
    
    # State-specific transitions
    if current_state == OnboardingState.INIT.value:
        return OnboardingState.INTENT_DISCOVERY.value
    
    elif current_state == OnboardingState.INTENT_DISCOVERY.value:
        # Move forward if user expressed motivation
        if len(user_message.split()) > 5:  # Basic heuristic
            return OnboardingState.PURPOSE_ORIENTATION.value
        return current_state
    
    elif current_state == OnboardingState.PURPOSE_ORIENTATION.value:
        return OnboardingState.ELIGIBILITY_CONFIRMATION.value
    
    elif current_state == OnboardingState.ELIGIBILITY_CONFIRMATION.value:
        # Check if basic info provided
        if len(missing_fields) < 3:
            return OnboardingState.CAPABILITY_DISCOVERY.value
        return current_state
    
    elif current_state == OnboardingState.CAPABILITY_DISCOVERY.value:
        # Move to confirmation if skills discussed
        if "skill" in user_message.lower() or len(missing_fields) < 2:
            return OnboardingState.PROFILE_CONFIRMATION.value
        return current_state
    
    elif current_state == OnboardingState.PROFILE_CONFIRMATION.value:
        # Check for confirmation signals
        confirm_signals = ["yes", "correct", "confirm", "looks good", "that's right", "accurate"]
        if any(signal in user_message.lower() for signal in confirm_signals):
            return OnboardingState.ONBOARDING_COMPLETE.value
        return current_state
    
    return current_state


def extract_fields_from_message(message: str) -> Dict[str, Any]:
    """
    Extract structured data from user message.
    Simple extraction for MVP - can be enhanced with NLP.
    """
    fields = {}
    message_lower = message.lower()
    
    # Extract name (simple heuristic)
    name_signals = ["my name is", "i'm ", "i am ", "call me "]
    for signal in name_signals:
        if signal in message_lower:
            start = message_lower.index(signal) + len(signal)
            # Take next 2-3 words as name
            words = message[start:].split()[:3]
            potential_name = " ".join(words).strip(".,!?")
            if potential_name:
                fields["full_name"] = potential_name.title()
                break
    
    # Extract email
    import re
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    emails = re.findall(email_pattern, message)
    if emails:
        fields["email"] = emails[0]
    
    # Extract skills (basic keyword matching)
    skill_keywords = ["programming", "teaching", "writing", "design", "marketing", 
                      "cooking", "driving", "languages", "healthcare", "construction",
                      "communication", "leadership", "organizing", "fundraising"]
    found_skills = [skill for skill in skill_keywords if skill in message_lower]
    if found_skills:
        fields["skills"] = found_skills
    
    # Extract location
    location_signals = ["i live in", "i'm from", "located in", "based in"]
    for signal in location_signals:
        if signal in message_lower:
            start = message_lower.index(signal) + len(signal)
            words = message[start:].split()[:3]
            potential_location = " ".join(words).strip(".,!?")
            if potential_location:
                fields["location"] = potential_location.title()
                break
    
    return fields


@onboarding_router.post("/turn", response_model=AgentTurnResponse)
async def process_turn(request: AgentTurnRequest):
    """
    Process a single conversation turn for onboarding.
    Core agent logic for the onboarding workflow.
    """
    session_state = request.session_state
    current_state = session_state.stage
    telemetry_events = []
    
    # Log user message event
    telemetry_events.append(TelemetryEvent(
        session_id=request.session_id,
        event_type=EventType.USER_MESSAGE,
        agent=AgentType.ONBOARDING,
        data={"message_length": len(request.user_message)}
    ))
    
    # Get missing fields from MCP
    missing_result = await call_mcp_capability("get-missing-fields", {
        "session_id": str(request.session_id)
    })
    
    missing_fields = missing_result.get("data", {}).get("missing_fields", [])
    confirmed_fields = missing_result.get("data", {}).get("confirmed_fields", {})
    
    # Extract any new fields from user message
    extracted_fields = extract_fields_from_message(request.user_message)
    if extracted_fields:
        await call_mcp_capability("save-confirmed-fields", {
            "session_id": str(request.session_id),
            "fields": extracted_fields
        })
        confirmed_fields.update(extracted_fields)
        missing_fields = [f for f in missing_fields if f not in extracted_fields]
    
    # Determine next state
    next_state = determine_next_state(current_state, request.user_message, missing_fields)
    
    # Log state transition if changed
    if next_state != current_state:
        telemetry_events.append(TelemetryEvent(
            session_id=request.session_id,
            event_type=EventType.STATE_TRANSITION,
            agent=AgentType.ONBOARDING,
            data={"from_state": current_state, "to_state": next_state}
        ))
    
    # Get system prompt for current/next state
    system_prompt = STATE_PROMPTS.get(next_state, STATE_PROMPTS[OnboardingState.INIT.value])
    
    # Add context about missing fields
    if missing_fields:
        system_prompt += f"\n\nNote: The following information is still needed: {', '.join(missing_fields)}. Naturally weave a question about one of these into your response."
    
    if confirmed_fields:
        system_prompt += f"\n\nConfirmed information so far: {confirmed_fields}"
    
    # Generate response using LLM
    assistant_message = await llm_adapter.generate_response(
        system_prompt=system_prompt,
        messages=request.conversation_history,
        user_message=request.user_message
    )
    
    # Log agent response
    telemetry_events.append(TelemetryEvent(
        session_id=request.session_id,
        event_type=EventType.AGENT_RESPONSE,
        agent=AgentType.ONBOARDING,
        data={"state": next_state, "response_length": len(assistant_message)}
    ))
    
    # Prepare handoff if onboarding complete
    handoff_event = None
    if next_state == OnboardingState.ONBOARDING_COMPLETE.value:
        handoff_event = HandoffEvent(
            session_id=request.session_id,
            from_agent=AgentType.ONBOARDING,
            to_agent=AgentType.SELECTION,
            handoff_type=HandoffType.AGENT_TRANSITION,
            payload={"confirmed_fields": confirmed_fields},
            reason="Onboarding completed successfully"
        )
    
    return AgentTurnResponse(
        assistant_message=assistant_message,
        active_agent=AgentType.ONBOARDING,
        workflow=session_state.workflow,
        state=next_state,
        sub_state=None,
        completion_status="complete" if next_state == OnboardingState.ONBOARDING_COMPLETE.value else "in_progress",
        confirmed_fields=confirmed_fields,
        missing_fields=missing_fields,
        handoff_event=handoff_event,
        telemetry_events=telemetry_events
    )


@onboarding_router.get("/health", response_model=HealthResponse)
async def onboarding_health():
    """Health check for onboarding agent service"""
    return HealthResponse(
        service="serve-onboarding-agent-service",
        status="healthy",
        version="1.0.0",
        timestamp=datetime.utcnow()
    )
