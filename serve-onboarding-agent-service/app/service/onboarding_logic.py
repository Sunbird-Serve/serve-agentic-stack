"""
SERVE Onboarding Agent Service - Onboarding Logic (Enhanced)
Autonomous agent for volunteer onboarding with eVidyaloka context

Key improvements:
- Dynamic question selection based on missing information
- Robust profile extraction from free-form text
- Autonomous state transitions based on collected data
- Pause/resume handling
- eVidyaloka-aligned warm communication
"""
from typing import List, Dict, Any, Optional, Tuple
import re
import logging

from app.schemas import (
    AgentTurnRequest, AgentTurnResponse, SessionState,
    HandoffEvent, TelemetryEvent, AgentType, WorkflowType,
    OnboardingState, EventType, HandoffType
)
from app.clients import domain_client
from app.service.llm_adapter import llm_adapter

logger = logging.getLogger(__name__)


# ============ State Machine Configuration ============

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

# Required fields for each stage progression
STAGE_REQUIREMENTS = {
    OnboardingState.ELIGIBILITY_CONFIRMATION.value: ["full_name", "email"],
    OnboardingState.CAPABILITY_DISCOVERY.value: ["skills"],
    OnboardingState.PROFILE_CONFIRMATION.value: ["full_name", "email", "skills"],
    OnboardingState.ONBOARDING_COMPLETE.value: ["full_name", "email", "skills", "availability"],
}


# ============ Profile Extraction ============

class ProfileExtractor:
    """
    Robust extraction of structured data from free-form conversation.
    
    Uses multiple strategies:
    1. Pattern matching for common formats
    2. Keyword-based extraction
    3. Context-aware parsing
    """
    
    # Name extraction patterns
    NAME_SIGNALS = [
        r"(?:my name is|i'm|i am|call me|this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        r"^([A-Z][a-z]+)(?:\s+here|,)",  # "Sarah here" or "Sarah,"
        r"(?:name[:\s]+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
    ]
    
    # Email pattern
    EMAIL_PATTERN = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    
    # Phone patterns (various formats)
    PHONE_PATTERNS = [
        r'\b(\+?\d{1,3}[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4})\b',
        r'\b(\d{10})\b',
        r'\b(\d{3}[-.\s]\d{3}[-.\s]\d{4})\b',
    ]
    
    # Location signals
    LOCATION_SIGNALS = [
        r"(?:i(?:'m| am)? (?:from|in|at|based in|living in|located in))\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:,\s*[A-Z][a-z]+)?)",
        r"(?:location[:\s]+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        r"(?:based out of|working from)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
    ]
    
    # Skill keywords and synonyms
    SKILL_KEYWORDS = {
        "teaching": ["teach", "teaching", "tutor", "tutoring", "instructor"],
        "mathematics": ["math", "maths", "mathematics", "algebra", "calculus", "arithmetic"],
        "science": ["science", "physics", "chemistry", "biology"],
        "english": ["english", "grammar", "writing", "reading", "literature"],
        "programming": ["programming", "coding", "code", "software", "computer", "python", "java"],
        "art": ["art", "drawing", "painting", "creative"],
        "music": ["music", "singing", "instrument", "guitar", "piano"],
        "languages": ["language", "hindi", "tamil", "telugu", "kannada", "spanish", "french"],
        "communication": ["communication", "speaking", "presentation"],
        "mentoring": ["mentor", "mentoring", "guidance", "counseling"],
        "sports": ["sports", "physical education", "fitness", "yoga"],
    }
    
    # Availability patterns
    AVAILABILITY_PATTERNS = [
        r"(\d+)\s*(?:hours?|hrs?)\s*(?:per|a|each)?\s*(?:week|wk)",
        r"(?:weekends?|saturday|sunday|weekdays?|evenings?|mornings?)",
        r"(?:few hours|couple of hours|some time)",
    ]
    
    def extract_all(self, message: str, existing_fields: Dict = None) -> Dict[str, Any]:
        """
        Extract all possible fields from a message.
        
        Args:
            message: User's message
            existing_fields: Already confirmed fields (to avoid overwriting)
            
        Returns:
            Dictionary of newly extracted fields
        """
        existing_fields = existing_fields or {}
        extracted = {}
        
        # Extract name (only if not already confirmed)
        if "full_name" not in existing_fields:
            name = self._extract_name(message)
            if name:
                extracted["full_name"] = name
        
        # Extract email
        if "email" not in existing_fields:
            email = self._extract_email(message)
            if email:
                extracted["email"] = email
        
        # Extract phone
        if "phone" not in existing_fields:
            phone = self._extract_phone(message)
            if phone:
                extracted["phone"] = phone
        
        # Extract location
        if "location" not in existing_fields:
            location = self._extract_location(message)
            if location:
                extracted["location"] = location
        
        # Extract skills (merge with existing)
        new_skills = self._extract_skills(message)
        if new_skills:
            existing_skills = existing_fields.get("skills", [])
            if isinstance(existing_skills, list):
                combined = list(set(existing_skills + new_skills))
                extracted["skills"] = combined
            else:
                extracted["skills"] = new_skills
        
        # Extract availability
        if "availability" not in existing_fields:
            availability = self._extract_availability(message)
            if availability:
                extracted["availability"] = availability
        
        return extracted
    
    def _extract_name(self, message: str) -> Optional[str]:
        """Extract name from message."""
        for pattern in self.NAME_SIGNALS:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Clean up - remove trailing articles and conjunctions
                name = self._clean_name(name)
                if name and len(name) > 1:
                    return name.title()
        return None
    
    def _clean_name(self, name: str) -> str:
        """Clean extracted name by removing trailing noise."""
        # Split into words
        words = name.split()
        clean_words = []
        
        # Stop words that indicate end of name
        stop_words = {'and', 'or', 'but', 'i', 'my', 'am', 'is', 'the', 'a', 'an',
                      'here', 'hi', 'hello', 'hey', 'want', 'would', 'like', 'to'}
        
        for word in words:
            if word.lower() in stop_words:
                break
            # Check if it looks like a name part (starts with capital or is all caps)
            if word[0].isupper() or word.isupper():
                clean_words.append(word)
            else:
                break
        
        return " ".join(clean_words[:3])  # Max 3 name parts
    
    def _extract_email(self, message: str) -> Optional[str]:
        """Extract email from message."""
        match = re.search(self.EMAIL_PATTERN, message)
        if match:
            return match.group(0).lower()
        return None
    
    def _extract_phone(self, message: str) -> Optional[str]:
        """Extract phone number from message."""
        for pattern in self.PHONE_PATTERNS:
            match = re.search(pattern, message)
            if match:
                return match.group(1)
        return None
    
    def _extract_location(self, message: str) -> Optional[str]:
        """Extract location from message."""
        for pattern in self.LOCATION_SIGNALS:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return match.group(1).strip().title()
        return None
    
    def _extract_skills(self, message: str) -> List[str]:
        """Extract skills from message."""
        found_skills = []
        message_lower = message.lower()
        
        for skill_name, keywords in self.SKILL_KEYWORDS.items():
            for keyword in keywords:
                if keyword in message_lower:
                    if skill_name not in found_skills:
                        found_skills.append(skill_name)
                    break
        
        return found_skills
    
    def _extract_availability(self, message: str) -> Optional[str]:
        """Extract availability information."""
        message_lower = message.lower()
        
        # Look for specific time commitments
        for pattern in self.AVAILABILITY_PATTERNS:
            match = re.search(pattern, message_lower)
            if match:
                return match.group(0)
        
        # Check for general availability keywords
        availability_keywords = ["weekend", "weekday", "evening", "morning", "flexible"]
        for keyword in availability_keywords:
            if keyword in message_lower:
                return keyword + "s" if not keyword.endswith("s") else keyword
        
        return None


# Singleton extractor
profile_extractor = ProfileExtractor()


# ============ State Determination ============

def determine_next_state(
    current_state: str,
    user_message: str,
    missing_fields: List[str],
    confirmed_fields: Dict
) -> Tuple[str, Optional[str]]:
    """
    Autonomously determine the next state based on:
    1. User signals (pause, exit, etc.)
    2. Data completeness
    3. Natural conversation flow
    
    Returns:
        Tuple of (next_state, reason)
    """
    message_lower = user_message.lower()
    
    # Check for pause/exit signals
    pause_signals = ["pause", "stop", "later", "bye", "quit", "exit", "not now", "another time"]
    if any(signal in message_lower for signal in pause_signals):
        return OnboardingState.PAUSED.value, "User requested to pause"
    
    # Check for resume signals (if currently paused)
    if current_state == OnboardingState.PAUSED.value:
        resume_signals = ["continue", "resume", "back", "ready", "let's go", "start"]
        if any(signal in message_lower for signal in resume_signals):
            # Resume to eligibility confirmation or wherever they left off
            return OnboardingState.ELIGIBILITY_CONFIRMATION.value, "User wants to resume"
    
    # State-specific logic
    if current_state == OnboardingState.INIT.value:
        # Always progress from init
        return OnboardingState.INTENT_DISCOVERY.value, "Initial greeting complete"
    
    elif current_state == OnboardingState.INTENT_DISCOVERY.value:
        # Progress if they've shared some motivation (message length check)
        if len(user_message.split()) > 3:
            return OnboardingState.PURPOSE_ORIENTATION.value, "User shared their motivation"
        return current_state, "Gathering more about motivation"
    
    elif current_state == OnboardingState.PURPOSE_ORIENTATION.value:
        # Progress to gather personal details
        return OnboardingState.ELIGIBILITY_CONFIRMATION.value, "Mission context shared"
    
    elif current_state == OnboardingState.ELIGIBILITY_CONFIRMATION.value:
        # Progress when we have basic info
        has_name = confirmed_fields.get("full_name")
        has_email = confirmed_fields.get("email")
        
        if has_name and has_email:
            return OnboardingState.CAPABILITY_DISCOVERY.value, "Basic profile complete"
        return current_state, "Collecting basic information"
    
    elif current_state == OnboardingState.CAPABILITY_DISCOVERY.value:
        # Progress when we have skills
        has_skills = confirmed_fields.get("skills") and len(confirmed_fields.get("skills", [])) > 0
        
        if has_skills:
            # Check if we have enough for profile confirmation
            has_availability = confirmed_fields.get("availability")
            if has_availability or len(missing_fields) <= 1:
                return OnboardingState.PROFILE_CONFIRMATION.value, "Skills captured"
        return current_state, "Gathering skills and availability"
    
    elif current_state == OnboardingState.PROFILE_CONFIRMATION.value:
        # Check for confirmation signals
        confirm_signals = ["yes", "correct", "confirm", "looks good", "that's right", 
                         "perfect", "accurate", "good", "ok", "okay", "yep", "yup"]
        if any(signal in message_lower for signal in confirm_signals):
            return OnboardingState.ONBOARDING_COMPLETE.value, "Profile confirmed"
        
        # Check for correction signals
        correction_signals = ["no", "wrong", "change", "update", "fix", "actually"]
        if any(signal in message_lower for signal in correction_signals):
            return OnboardingState.CAPABILITY_DISCOVERY.value, "User wants to update profile"
        
        return current_state, "Awaiting profile confirmation"
    
    elif current_state == OnboardingState.ONBOARDING_COMPLETE.value:
        # Terminal state
        return current_state, "Onboarding complete"
    
    return current_state, "Continuing current stage"


def evaluate_readiness(confirmed_fields: Dict) -> Tuple[bool, List[str]]:
    """
    Evaluate if the volunteer is ready to proceed to selection.
    
    Returns:
        Tuple of (is_ready, missing_required_fields)
    """
    required = ["full_name", "email", "skills", "availability"]
    missing = []
    
    for field in required:
        value = confirmed_fields.get(field)
        if not value or (isinstance(value, list) and len(value) == 0):
            missing.append(field)
    
    return len(missing) == 0, missing


# ============ Main Service ============

class OnboardingAgentService:
    """
    Autonomous onboarding agent service with memory capabilities.
    
    Responsibilities:
    - Process conversation turns
    - Extract profile data autonomously
    - Manage state transitions
    - Evaluate volunteer readiness
    - Generate and use conversation memory summaries
    """
    
    def __init__(self):
        from app.service.memory_service import memory_service
        self.memory_service = memory_service
    
    async def process_turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
        """
        Process a single conversation turn for onboarding.
        
        Flow:
        1. Log incoming message
        2. Get current profile state from MCP
        3. Get memory context for returning volunteers
        4. Extract new data from message
        5. Save extracted data
        6. Determine next state
        7. Generate contextual response with memory
        8. Update memory summary if needed
        9. Prepare handoff if complete
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
        
        # Get current profile state from MCP
        missing_result = await domain_client.get_missing_fields(request.session_id)
        missing_fields = missing_result.get("data", {}).get("missing_fields", [])
        confirmed_fields = missing_result.get("data", {}).get("confirmed_fields", {})
        
        # Get memory context for returning volunteers
        memory_context = await self.memory_service.get_memory_context(
            session_id=str(request.session_id),
            confirmed_fields=confirmed_fields,
            domain_client=domain_client
        )
        
        if memory_context:
            logger.info(f"Using memory context for session {str(request.session_id)[:8]}...")
            telemetry_events.append(TelemetryEvent(
                session_id=request.session_id,
                event_type=EventType.MCP_CALL,
                agent=AgentType.ONBOARDING,
                data={"action": "get_memory_context", "has_context": True}
            ))
        
        # Extract new fields from user message
        extracted_fields = profile_extractor.extract_all(
            request.user_message,
            existing_fields=confirmed_fields
        )
        
        # Save extracted fields to MCP
        if extracted_fields:
            await domain_client.save_confirmed_fields(request.session_id, extracted_fields)
            confirmed_fields.update(extracted_fields)
            # Update missing fields list
            missing_fields = [f for f in missing_fields if f not in extracted_fields]
            
            logger.info(f"Extracted fields: {list(extracted_fields.keys())}")
            telemetry_events.append(TelemetryEvent(
                session_id=request.session_id,
                event_type=EventType.MCP_CALL,
                agent=AgentType.ONBOARDING,
                data={"action": "save_fields", "fields": list(extracted_fields.keys())}
            ))
        
        # Determine next state autonomously
        next_state, transition_reason = determine_next_state(
            current_state,
            request.user_message,
            missing_fields,
            confirmed_fields
        )
        
        # Log state transition if changed
        if next_state != current_state:
            telemetry_events.append(TelemetryEvent(
                session_id=request.session_id,
                event_type=EventType.STATE_TRANSITION,
                agent=AgentType.ONBOARDING,
                data={
                    "from_state": current_state,
                    "to_state": next_state,
                    "reason": transition_reason
                }
            ))
            logger.info(f"State transition: {current_state} -> {next_state} ({transition_reason})")
        
        # Generate contextual response with memory
        assistant_message = await llm_adapter.generate_response(
            stage=next_state,
            messages=request.conversation_history,
            user_message=request.user_message,
            missing_fields=missing_fields,
            confirmed_fields=confirmed_fields,
            memory_context=memory_context
        )
        
        # Log agent response
        telemetry_events.append(TelemetryEvent(
            session_id=request.session_id,
            event_type=EventType.AGENT_RESPONSE,
            agent=AgentType.ONBOARDING,
            data={
                "state": next_state,
                "response_length": len(assistant_message),
                "fields_confirmed": len(confirmed_fields),
                "fields_missing": len(missing_fields),
                "used_memory": bool(memory_context)
            }
        ))
        
        # Update memory summary periodically
        conversation_with_new = request.conversation_history + [
            {"role": "user", "content": request.user_message},
            {"role": "assistant", "content": assistant_message}
        ]
        
        summary_result = await self.memory_service.process_conversation_update(
            session_id=str(request.session_id),
            conversation=conversation_with_new,
            domain_client=domain_client
        )
        
        if summary_result:
            telemetry_events.append(TelemetryEvent(
                session_id=request.session_id,
                event_type=EventType.MCP_CALL,
                agent=AgentType.ONBOARDING,
                data={
                    "action": "save_memory_summary",
                    "key_facts_count": len(summary_result.get("key_facts", []))
                }
            ))
        
        # Evaluate readiness and prepare handoff if complete
        handoff_event = None
        completion_status = "in_progress"
        
        if next_state == OnboardingState.ONBOARDING_COMPLETE.value:
            is_ready, missing_required = evaluate_readiness(confirmed_fields)
            
            if is_ready:
                completion_status = "complete"
                
                # Generate final summary before handoff
                final_summary = await self.memory_service.process_conversation_update(
                    session_id=str(request.session_id),
                    conversation=conversation_with_new,
                    domain_client=domain_client
                )
                
                handoff_event = HandoffEvent(
                    session_id=request.session_id,
                    from_agent=AgentType.ONBOARDING,
                    to_agent=AgentType.SELECTION,
                    handoff_type=HandoffType.AGENT_TRANSITION,
                    payload={
                        "confirmed_fields": confirmed_fields,
                        "memory_summary": final_summary.get("summary_text") if final_summary else None,
                        "key_facts": final_summary.get("key_facts", []) if final_summary else [],
                        "readiness": {
                            "is_ready": True,
                            "profile_complete": True
                        }
                    },
                    reason="Onboarding completed - volunteer ready for selection"
                )
                logger.info(f"Handoff prepared: {AgentType.ONBOARDING.value} -> {AgentType.SELECTION.value}")
            else:
                logger.warning(f"Onboarding marked complete but missing: {missing_required}")
        
        elif next_state == OnboardingState.PAUSED.value:
            completion_status = "paused"
            # Generate summary when pausing so we remember context
            await self.memory_service.process_conversation_update(
                session_id=str(request.session_id),
                conversation=conversation_with_new,
                domain_client=domain_client
            )
        
        return AgentTurnResponse(
            assistant_message=assistant_message,
            active_agent=AgentType.ONBOARDING,
            workflow=WorkflowType(session_state.workflow),
            state=next_state,
            sub_state=None,
            completion_status=completion_status,
            confirmed_fields=confirmed_fields,
            missing_fields=missing_fields,
            handoff_event=handoff_event,
            telemetry_events=telemetry_events
        )


# Singleton instance
onboarding_agent_service = OnboardingAgentService()
