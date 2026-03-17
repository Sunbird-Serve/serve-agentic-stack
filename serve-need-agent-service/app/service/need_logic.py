"""
SERVE Need Agent Service - Core Logic
Autonomous agent for need coordination with eVidyaloka context.

Key responsibilities:
- Resolve coordinator identity (linked/unlinked/ambiguous)
- Resolve school context (existing/new/ambiguous)
- Capture need details through conversation
- Validate completeness before submission
- Handle pause/resume
- Escalate ambiguous cases for human review
"""
import re
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date

from app.schemas.need_schemas import (
    NeedWorkflowState, CoordinatorResolutionStatus, SchoolResolutionStatus,
    NeedStatus, NeedEventType, NeedSessionState, NeedAgentTurnRequest,
    NeedAgentTurnResponse, NeedDraft, Coordinator, School,
    MANDATORY_NEED_FIELDS, SUBJECT_OPTIONS, GRADE_LEVEL_OPTIONS
)
from app.clients import domain_client
from app.service.llm_adapter import llm_adapter

logger = logging.getLogger(__name__)


# ============ State Transitions ============

VALID_NEED_TRANSITIONS = {
    NeedWorkflowState.INITIATED.value: [
        NeedWorkflowState.RESOLVING_COORDINATOR.value,
        NeedWorkflowState.PAUSED.value
    ],
    NeedWorkflowState.RESOLVING_COORDINATOR.value: [
        NeedWorkflowState.RESOLVING_SCHOOL.value,
        NeedWorkflowState.HUMAN_REVIEW.value,
        NeedWorkflowState.PAUSED.value
    ],
    NeedWorkflowState.RESOLVING_SCHOOL.value: [
        NeedWorkflowState.DRAFTING_NEED.value,
        NeedWorkflowState.HUMAN_REVIEW.value,
        NeedWorkflowState.PAUSED.value
    ],
    NeedWorkflowState.DRAFTING_NEED.value: [
        NeedWorkflowState.PENDING_APPROVAL.value,
        NeedWorkflowState.PAUSED.value
    ],
    NeedWorkflowState.PENDING_APPROVAL.value: [
        NeedWorkflowState.APPROVED.value,
        NeedWorkflowState.REFINEMENT_REQUIRED.value,
        NeedWorkflowState.REJECTED.value,
        NeedWorkflowState.PAUSED.value
    ],
    NeedWorkflowState.REFINEMENT_REQUIRED.value: [
        NeedWorkflowState.DRAFTING_NEED.value,
        NeedWorkflowState.PENDING_APPROVAL.value,
        NeedWorkflowState.PAUSED.value
    ],
    NeedWorkflowState.APPROVED.value: [
        NeedWorkflowState.FULFILLMENT_HANDOFF_READY.value
    ],
    NeedWorkflowState.PAUSED.value: [
        NeedWorkflowState.INITIATED.value,
        NeedWorkflowState.RESOLVING_COORDINATOR.value,
        NeedWorkflowState.RESOLVING_SCHOOL.value,
        NeedWorkflowState.DRAFTING_NEED.value,
        NeedWorkflowState.PENDING_APPROVAL.value,
        NeedWorkflowState.REFINEMENT_REQUIRED.value
    ],
    NeedWorkflowState.HUMAN_REVIEW.value: [
        NeedWorkflowState.RESOLVING_COORDINATOR.value,
        NeedWorkflowState.RESOLVING_SCHOOL.value,
        NeedWorkflowState.DRAFTING_NEED.value,
        NeedWorkflowState.REJECTED.value
    ],
    NeedWorkflowState.REJECTED.value: [],
    NeedWorkflowState.FULFILLMENT_HANDOFF_READY.value: []
}


# ============ Need Detail Extraction ============

class NeedDetailExtractor:
    """Extract structured need details from free-form conversation."""
    
    # Subject keyword mapping
    SUBJECT_KEYWORDS = {
        "mathematics": ["math", "maths", "mathematics", "arithmetic", "algebra", "geometry"],
        "science": ["science", "physics", "chemistry", "biology", "natural science"],
        "english": ["english", "grammar", "writing", "reading", "literature", "spoken english"],
        "hindi": ["hindi", "hindustani"],
        "social_studies": ["social", "history", "geography", "civics", "social studies"],
        "computer_basics": ["computer", "computers", "computing", "it", "technology"],
        "spoken_english": ["spoken english", "speaking english", "english speaking", "conversation english"],
        "art": ["art", "drawing", "painting", "craft"],
        "music": ["music", "singing", "songs"]
    }
    
    # Grade patterns
    GRADE_PATTERNS = [
        r"(?:grade|class|std|standard)\s*(\d{1,2})",
        r"(\d{1,2})(?:th|st|nd|rd)?\s*(?:grade|class|std|standard)",
        r"(\d{1,2})(?:th|st|nd|rd)?\s*graders?"
    ]
    
    # Student count patterns
    STUDENT_COUNT_PATTERNS = [
        r"(\d+)\s*(?:students?|children|kids|learners)",
        r"(?:around|about|approximately|approx)\s*(\d+)",
        r"(?:total|count|number)[:\s]*(\d+)"
    ]
    
    # Time slot patterns
    TIME_PATTERNS = [
        r"(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))",
        r"(morning|afternoon|evening)",
        r"(weekday|weekend|saturday|sunday|monday|tuesday|wednesday|thursday|friday)"
    ]
    
    # Duration patterns
    DURATION_PATTERNS = [
        r"(\d+)\s*(?:weeks?|wks?)",
        r"(\d+)\s*(?:months?)\s*",  # Convert to weeks
        r"(?:for|about)\s*(\d+)\s*(?:weeks?|months?)"
    ]
    
    def extract_all(self, message: str, existing_draft: Optional[Dict] = None) -> Dict[str, Any]:
        """Extract all possible need details from a message."""
        existing_draft = existing_draft or {}
        extracted = {}
        message_lower = message.lower()
        
        # Extract subjects
        subjects = self._extract_subjects(message_lower)
        if subjects:
            existing_subjects = existing_draft.get("subjects", [])
            combined = list(set(existing_subjects + subjects))
            extracted["subjects"] = combined
        
        # Extract grades
        grades = self._extract_grades(message)
        if grades:
            existing_grades = existing_draft.get("grade_levels", [])
            combined = list(set(existing_grades + grades))
            extracted["grade_levels"] = combined
        
        # Extract student count
        count = self._extract_student_count(message)
        if count and "student_count" not in existing_draft:
            extracted["student_count"] = count
        
        # Extract time slots
        slots = self._extract_time_slots(message_lower)
        if slots:
            existing_slots = existing_draft.get("time_slots", [])
            combined = list(set(existing_slots + slots))
            extracted["time_slots"] = combined
        
        # Extract start date
        start_date = self._extract_start_date(message_lower)
        if start_date and "start_date" not in existing_draft:
            extracted["start_date"] = start_date
        
        # Extract duration
        duration = self._extract_duration(message_lower)
        if duration and "duration_weeks" not in existing_draft:
            extracted["duration_weeks"] = duration
        
        return extracted
    
    def _extract_subjects(self, message: str) -> List[str]:
        """Extract subject mentions from message."""
        found = []
        for subject, keywords in self.SUBJECT_KEYWORDS.items():
            for keyword in keywords:
                if keyword in message:
                    if subject not in found:
                        found.append(subject)
                    break
        return found
    
    def _extract_grades(self, message: str) -> List[str]:
        """Extract grade levels from message."""
        found = set()
        for pattern in self.GRADE_PATTERNS:
            matches = re.findall(pattern, message, re.IGNORECASE)
            for match in matches:
                grade = str(int(match))  # Normalize
                if 1 <= int(grade) <= 12:
                    found.add(grade)
        
        # Also check for grade ranges like "5-8"
        range_pattern = r"(\d{1,2})\s*(?:to|-)\s*(\d{1,2})"
        range_matches = re.findall(range_pattern, message)
        for start, end in range_matches:
            for g in range(int(start), int(end) + 1):
                if 1 <= g <= 12:
                    found.add(str(g))
        
        return list(found)
    
    def _extract_student_count(self, message: str) -> Optional[int]:
        """Extract student count from message."""
        for pattern in self.STUDENT_COUNT_PATTERNS:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                count = int(match.group(1))
                if 1 <= count <= 1000:  # Reasonable bounds
                    return count
        return None
    
    def _extract_time_slots(self, message: str) -> List[str]:
        """Extract time slot preferences from message."""
        found = []
        for pattern in self.TIME_PATTERNS:
            matches = re.findall(pattern, message, re.IGNORECASE)
            found.extend(matches)
        return list(set(found))
    
    def _extract_start_date(self, message: str) -> Optional[str]:
        """Extract start date from message."""
        # Check for relative dates
        today = date.today()
        
        if "next week" in message:
            # Next Monday
            days_ahead = 7 - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            from datetime import timedelta
            next_monday = today + timedelta(days=days_ahead)
            return next_monday.isoformat()
        
        if "next month" in message:
            # First of next month
            if today.month == 12:
                return f"{today.year + 1}-01-01"
            return f"{today.year}-{today.month + 1:02d}-01"
        
        if "immediately" in message or "asap" in message or "as soon as" in message:
            return today.isoformat()
        
        # Look for specific date patterns
        date_pattern = r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})"
        match = re.search(date_pattern, message)
        if match:
            day, month, year = match.groups()
            if len(year) == 2:
                year = f"20{year}"
            try:
                parsed = date(int(year), int(month), int(day))
                return parsed.isoformat()
            except ValueError:
                pass
        
        return None
    
    def _extract_duration(self, message: str) -> Optional[int]:
        """Extract duration in weeks from message."""
        for pattern in self.DURATION_PATTERNS:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                value = int(match.group(1))
                # Convert months to weeks if needed
                if "month" in message[match.start():match.end()].lower():
                    value = value * 4
                if 1 <= value <= 52:
                    return value
        return None
    
    def extract_coordinator_info(self, message: str) -> Dict[str, Any]:
        """Extract coordinator information from introduction."""
        info = {}
        
        # Name patterns
        name_patterns = [
            r"(?:my name is|i'm|i am|this is|call me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            r"^([A-Z][a-z]+)(?:\s+here|,|\s+from)",
        ]
        for pattern in name_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                name = match.group(1).strip().title()
                # Clean trailing words
                stop_words = {'and', 'from', 'at', 'the', 'i', 'am', 'here'}
                words = name.split()
                clean = []
                for w in words:
                    if w.lower() in stop_words:
                        break
                    clean.append(w)
                if clean:
                    info["name"] = " ".join(clean[:3])
                break
        
        # Phone/WhatsApp patterns
        phone_pattern = r"(\+?\d{10,12})"
        match = re.search(phone_pattern, message)
        if match:
            info["whatsapp_number"] = match.group(1)
        
        return info
    
    def extract_school_info(self, message: str) -> Dict[str, Any]:
        """Extract school information from message."""
        info = {}
        
        # School name patterns
        school_patterns = [
            r"(?:school|vidyalaya|vidya|shala)[:\s]+([A-Za-z\s]+?)(?:,|\.|\sin|\sat|$)",
            r"(?:from|at|represent)\s+([A-Za-z\s]+?)\s+(?:school|vidyalaya)",
        ]
        for pattern in school_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                school_name = match.group(1).strip().title()
                if len(school_name) > 3:
                    info["name"] = school_name
                break
        
        # Location patterns
        location_patterns = [
            r"(?:in|at|from|located in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            r"(?:village|town|city|district)[:\s]+([A-Za-z\s]+?)(?:,|\.|\s|$)",
        ]
        for pattern in location_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                location = match.group(1).strip().title()
                if len(location) > 2 and location.lower() not in ['school', 'vidyalaya']:
                    info["location"] = location
                break
        
        return info


# Singleton extractor
need_extractor = NeedDetailExtractor()


# ============ State Determination ============

def determine_next_need_state(
    current_state: str,
    user_message: str,
    coordinator_resolved: bool,
    school_resolved: bool,
    need_draft: Optional[Dict],
    missing_fields: List[str]
) -> Tuple[str, str]:
    """
    Autonomously determine the next state based on:
    1. User signals (pause, confirm, etc.)
    2. Resolution status
    3. Data completeness
    
    Returns: (next_state, reason)
    """
    message_lower = user_message.lower()
    
    # Check for pause signals
    pause_signals = ["pause", "stop", "later", "bye", "quit", "not now", "come back"]
    if any(signal in message_lower for signal in pause_signals):
        return NeedWorkflowState.PAUSED.value, "User requested pause"
    
    # Check for resume signals (if paused)
    if current_state == NeedWorkflowState.PAUSED.value:
        resume_signals = ["continue", "resume", "ready", "back", "let's go", "start"]
        if any(signal in message_lower for signal in resume_signals):
            # Return to appropriate state based on progress
            if not coordinator_resolved:
                return NeedWorkflowState.RESOLVING_COORDINATOR.value, "Resuming coordinator resolution"
            elif not school_resolved:
                return NeedWorkflowState.RESOLVING_SCHOOL.value, "Resuming school resolution"
            elif missing_fields:
                return NeedWorkflowState.DRAFTING_NEED.value, "Resuming need drafting"
            else:
                return NeedWorkflowState.PENDING_APPROVAL.value, "Resuming for confirmation"
    
    # State-specific logic
    if current_state == NeedWorkflowState.INITIATED.value:
        return NeedWorkflowState.RESOLVING_COORDINATOR.value, "Starting coordinator resolution"
    
    elif current_state == NeedWorkflowState.RESOLVING_COORDINATOR.value:
        if coordinator_resolved:
            return NeedWorkflowState.RESOLVING_SCHOOL.value, "Coordinator resolved, moving to school"
        return current_state, "Awaiting coordinator details"
    
    elif current_state == NeedWorkflowState.RESOLVING_SCHOOL.value:
        if school_resolved:
            return NeedWorkflowState.DRAFTING_NEED.value, "School resolved, starting need capture"
        return current_state, "Awaiting school details"
    
    elif current_state == NeedWorkflowState.DRAFTING_NEED.value:
        # Check if all mandatory fields are captured
        if not missing_fields:
            return NeedWorkflowState.PENDING_APPROVAL.value, "All details captured, ready for confirmation"
        return current_state, f"Still gathering: {', '.join(missing_fields[:2])}"
    
    elif current_state == NeedWorkflowState.PENDING_APPROVAL.value:
        # Check for confirmation
        confirm_signals = ["yes", "correct", "confirm", "looks good", "that's right", "perfect", "ok", "okay", "approved", "submit"]
        if any(signal in message_lower for signal in confirm_signals):
            return NeedWorkflowState.APPROVED.value, "Coordinator confirmed the need"
        
        # Check for changes requested
        change_signals = ["no", "wrong", "change", "update", "fix", "actually", "wait"]
        if any(signal in message_lower for signal in change_signals):
            return NeedWorkflowState.DRAFTING_NEED.value, "Coordinator wants to make changes"
        
        return current_state, "Awaiting confirmation"
    
    elif current_state == NeedWorkflowState.APPROVED.value:
        return NeedWorkflowState.FULFILLMENT_HANDOFF_READY.value, "Ready for fulfillment handoff"
    
    elif current_state == NeedWorkflowState.REFINEMENT_REQUIRED.value:
        # After addressing refinement, go back to drafting
        return NeedWorkflowState.DRAFTING_NEED.value, "Addressing refinement feedback"
    
    return current_state, "Continuing in current state"


# ============ Main Service ============

class NeedAgentService:
    """
    Autonomous need agent service.
    
    Responsibilities:
    - Process conversation turns for need coordination
    - Resolve coordinator and school identity
    - Capture and validate need details
    - Manage state transitions
    - Prepare for approval and fulfillment handoff
    """
    
    def __init__(self):
        self.extractor = need_extractor
    
    async def process_turn(self, request: NeedAgentTurnRequest) -> NeedAgentTurnResponse:
        """
        Process a single conversation turn.
        
        Flow:
        1. Log incoming message
        2. Extract information based on current state
        3. Update draft/context as needed
        4. Determine next state
        5. Generate response
        6. Prepare handoff if approved
        """
        session_state = request.session_state
        current_state = session_state.stage
        telemetry_events = []
        
        # Track context
        coordinator_context = None
        school_context = None
        need_draft = {}
        
        # Log user message event
        telemetry_events.append({
            "session_id": str(request.session_id),
            "event_type": NeedEventType.SESSION_START.value if current_state == NeedWorkflowState.INITIATED.value else "user_message",
            "agent": "need",
            "data": {"message_length": len(request.user_message)}
        })
        
        # Get existing context from domain service
        context_result = await domain_client.resume_need_context(str(request.session_id))
        if context_result.get("status") == "success" and context_result.get("data"):
            ctx = context_result["data"]
            coordinator_context = ctx.get("coordinator")
            school_context = ctx.get("school")
            need_draft = ctx.get("need_draft", {})
        
        # Process based on current state
        coordinator_resolved = session_state.coordinator_resolution == CoordinatorResolutionStatus.VERIFIED
        school_resolved = session_state.school_resolution in [SchoolResolutionStatus.EXISTING, SchoolResolutionStatus.NEW]
        
        # Extract information from message
        if current_state in [NeedWorkflowState.INITIATED.value, NeedWorkflowState.RESOLVING_COORDINATOR.value]:
            # Extract coordinator info
            coord_info = self.extractor.extract_coordinator_info(request.user_message)
            if coord_info:
                if not coordinator_context:
                    coordinator_context = {}
                coordinator_context.update(coord_info)
                
                # Try to resolve coordinator identity
                if coord_info.get("name") or request.channel_metadata.get("whatsapp_number") if request.channel_metadata else None:
                    whatsapp = request.channel_metadata.get("whatsapp_number", "") if request.channel_metadata else ""
                    resolve_result = await domain_client.resolve_coordinator_identity(
                        whatsapp_number=whatsapp,
                        name=coord_info.get("name")
                    )
                    if resolve_result.get("status") == "success":
                        resolution_data = resolve_result.get("data", {})
                        if resolution_data.get("coordinator"):
                            coordinator_context = resolution_data["coordinator"]
                            coordinator_resolved = True
                            session_state.coordinator_resolution = CoordinatorResolutionStatus.VERIFIED
        
        if current_state in [NeedWorkflowState.RESOLVING_SCHOOL.value]:
            # Extract school info
            school_info = self.extractor.extract_school_info(request.user_message)
            if school_info:
                if not school_context:
                    school_context = {}
                school_context.update(school_info)
                
                # Try to resolve school context
                resolve_result = await domain_client.resolve_school_context(
                    coordinator_id=session_state.coordinator_id,
                    school_hint=school_info.get("name")
                )
                if resolve_result.get("status") == "success":
                    resolution_data = resolve_result.get("data", {})
                    if resolution_data.get("school"):
                        school_context = resolution_data["school"]
                        school_resolved = True
                        session_state.school_resolution = SchoolResolutionStatus.EXISTING
                    elif school_info.get("name") and school_info.get("location"):
                        # Create new school
                        create_result = await domain_client.create_basic_school_context(
                            name=school_info["name"],
                            location=school_info.get("location", ""),
                            contact_number=coordinator_context.get("whatsapp_number") if coordinator_context else None
                        )
                        if create_result.get("status") == "success":
                            school_context = create_result.get("data", {}).get("school")
                            school_resolved = True
                            session_state.school_resolution = SchoolResolutionStatus.NEW
        
        if current_state == NeedWorkflowState.DRAFTING_NEED.value:
            # Extract need details
            extracted = self.extractor.extract_all(request.user_message, need_draft)
            if extracted:
                need_draft.update(extracted)
                
                # Save updated draft
                await domain_client.create_or_update_need_draft(
                    session_id=str(request.session_id),
                    need_data=need_draft
                )
                
                telemetry_events.append({
                    "session_id": str(request.session_id),
                    "event_type": NeedEventType.NEED_DRAFT_UPDATED.value,
                    "agent": "need",
                    "data": {"fields_updated": list(extracted.keys())}
                })
        
        # Calculate missing fields
        missing_fields = self._get_missing_fields(need_draft)
        completion_pct = self._calculate_completion(need_draft)
        
        # Determine next state
        next_state, transition_reason = determine_next_need_state(
            current_state=current_state,
            user_message=request.user_message,
            coordinator_resolved=coordinator_resolved,
            school_resolved=school_resolved,
            need_draft=need_draft,
            missing_fields=missing_fields
        )
        
        # Log state transition
        if next_state != current_state:
            telemetry_events.append({
                "session_id": str(request.session_id),
                "event_type": NeedEventType.STATUS_CHANGED.value,
                "agent": "need",
                "data": {
                    "from_state": current_state,
                    "to_state": next_state,
                    "reason": transition_reason
                }
            })
            logger.info(f"Need state transition: {current_state} -> {next_state} ({transition_reason})")
        
        # Generate response
        assistant_message = await llm_adapter.generate_response(
            stage=next_state,
            messages=request.conversation_history,
            user_message=request.user_message,
            coordinator_context=coordinator_context,
            school_context=school_context,
            need_draft=need_draft,
            missing_fields=missing_fields
        )
        
        # Prepare handoff if approved
        handoff_event = None
        completion_status = "in_progress"
        
        if next_state == NeedWorkflowState.APPROVED.value:
            completion_status = "approved"
            
            # Prepare fulfillment handoff
            handoff_result = await domain_client.prepare_fulfillment_handoff(
                need_id=need_draft.get("id", str(request.session_id))
            )
            
            if handoff_result.get("status") == "success":
                handoff_event = {
                    "session_id": str(request.session_id),
                    "from_agent": "need",
                    "to_agent": "fulfillment",
                    "handoff_type": "agent_transition",
                    "payload": handoff_result.get("data", {}),
                    "reason": "Need approved, ready for volunteer matching"
                }
                
                telemetry_events.append({
                    "session_id": str(request.session_id),
                    "event_type": NeedEventType.HANDOFF_PREPARED.value,
                    "agent": "need",
                    "data": {"target_agent": "fulfillment"}
                })
        
        elif next_state == NeedWorkflowState.PAUSED.value:
            completion_status = "paused"
            telemetry_events.append({
                "session_id": str(request.session_id),
                "event_type": NeedEventType.SESSION_PAUSED.value,
                "agent": "need",
                "data": {}
            })
        
        elif next_state == NeedWorkflowState.HUMAN_REVIEW.value:
            completion_status = "human_review"
            telemetry_events.append({
                "session_id": str(request.session_id),
                "event_type": NeedEventType.HUMAN_REVIEW_ESCALATED.value,
                "agent": "need",
                "data": {"reason": transition_reason}
            })
        
        # Build response
        return NeedAgentTurnResponse(
            assistant_message=assistant_message,
            active_agent="need",
            workflow="need_lifecycle",
            state=next_state,
            completion_status=completion_status,
            coordinator_resolved=Coordinator(**coordinator_context) if coordinator_context and coordinator_context.get("name") else None,
            school_resolved=School(**school_context) if school_context and school_context.get("name") else None,
            need_draft=NeedDraft(**need_draft) if need_draft else None,
            missing_fields=missing_fields,
            completion_percentage=completion_pct,
            telemetry_events=telemetry_events,
            handoff_event=handoff_event
        )
    
    def _get_missing_fields(self, draft: Dict) -> List[str]:
        """Get list of missing mandatory fields."""
        missing = []
        for field in MANDATORY_NEED_FIELDS:
            value = draft.get(field)
            if not value or (isinstance(value, list) and len(value) == 0):
                missing.append(field)
        return missing
    
    def _calculate_completion(self, draft: Dict) -> int:
        """Calculate completion percentage."""
        if not draft:
            return 0
        
        total_fields = len(MANDATORY_NEED_FIELDS)
        filled = 0
        
        for field in MANDATORY_NEED_FIELDS:
            value = draft.get(field)
            if value and (not isinstance(value, list) or len(value) > 0):
                filled += 1
        
        return round((filled / total_fields) * 100)


# Singleton instance
need_agent_service = NeedAgentService()
