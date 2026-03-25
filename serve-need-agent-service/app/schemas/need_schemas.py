"""
SERVE Need Agent Service - Schemas
Pydantic models for need lifecycle management.
"""
from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import date
from pydantic import BaseModel, Field
from enum import Enum


# ============ Enums ============

class NeedWorkflowState(str, Enum):
    """States in the need lifecycle workflow."""
    INITIATED = "initiated"
    CAPTURING_PHONE = "capturing_phone"          # web UI: ask for phone before identity lookup
    RESOLVING_COORDINATOR = "resolving_coordinator"
    CONFIRMING_IDENTITY = "confirming_identity"  # coordinator+school resolved, awaiting confirmation
    RESOLVING_SCHOOL = "resolving_school"
    DRAFTING_NEED = "drafting_need"
    PENDING_APPROVAL = "pending_approval"
    REFINEMENT_REQUIRED = "refinement_required"
    SUBMITTED = "submitted"                      # need raised in Serve Need Service (auto-approved)
    APPROVED = "approved"                        # kept for compatibility
    PAUSED = "paused"
    REJECTED = "rejected"
    HUMAN_REVIEW = "human_review"
    FULFILLMENT_HANDOFF_READY = "fulfillment_handoff_ready"


class CoordinatorResolutionStatus(str, Enum):
    """Status of coordinator identity resolution."""
    LINKED = "linked"           # Known coordinator with linked school(s)
    UNLINKED = "unlinked"       # New number, needs mapping or school creation
    AMBIGUOUS = "ambiguous"     # Multiple matches, needs clarification
    VERIFIED = "verified"       # Explicitly verified by coordinator


class SchoolResolutionStatus(str, Enum):
    """Status of school context resolution."""
    EXISTING = "existing"       # Known school in system
    NEW = "new"                 # New school, needs creation
    AMBIGUOUS = "ambiguous"     # Unclear, needs human review


class NeedStatus(str, Enum):
    """Status of a need record."""
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REFINEMENT_REQUIRED = "refinement_required"
    PAUSED = "paused"
    REJECTED = "rejected"
    FULFILLED = "fulfilled"


class NeedEventType(str, Enum):
    """Types of events in need lifecycle."""
    SESSION_START = "session_start"
    COORDINATOR_RESOLVED = "coordinator_resolved"
    SCHOOL_RESOLVED = "school_resolved"
    NEED_DRAFT_CREATED = "need_draft_created"
    NEED_DRAFT_UPDATED = "need_draft_updated"
    NEED_SUBMITTED = "need_submitted"
    APPROVAL_DECISION = "approval_decision"
    REFINEMENT_REQUESTED = "refinement_requested"
    STATUS_CHANGED = "status_changed"
    HANDOFF_PREPARED = "handoff_prepared"
    SESSION_PAUSED = "session_paused"
    SESSION_RESUMED = "session_resumed"
    HUMAN_REVIEW_ESCALATED = "human_review_escalated"


# ============ Core Models ============

class Coordinator(BaseModel):
    """Coordinator profile."""
    id: Optional[str] = None
    name: str
    whatsapp_number: Optional[str] = None  # not always available via web UI channel
    email: Optional[str] = None
    school_ids: List[str] = Field(default_factory=list)
    is_verified: bool = False


class School(BaseModel):
    """School context."""
    id: Optional[str] = None
    name: str
    location: Optional[str] = None  # not always provided during initial drafting
    contact_number: Optional[str] = None
    coordinator_ids: List[str] = Field(default_factory=list)
    previous_needs: List[str] = Field(default_factory=list)


class NeedDraft(BaseModel):
    """Draft need being captured."""
    id: Optional[str] = None
    session_id: str
    school_id: Optional[str] = None
    coordinator_id: Optional[str] = None
    
    # Core need attributes
    subjects: List[str] = Field(default_factory=list)
    grade_levels: List[str] = Field(default_factory=list)
    student_count: Optional[int] = None
    time_slots: List[str] = Field(default_factory=list)
    schedule_preference: Optional[str] = None
    start_date: Optional[date] = None
    duration_weeks: Optional[int] = None
    
    # Additional context
    special_requirements: Optional[str] = None
    previous_need_reference: Optional[str] = None
    
    # Status tracking
    status: NeedStatus = NeedStatus.DRAFT
    admin_comments: Optional[str] = None
    
    class Config:
        json_encoders = {
            date: lambda v: v.isoformat() if v else None
        }


# ============ Request/Response Models ============

class NeedSessionState(BaseModel):
    """Current state of a need session."""
    id: UUID
    channel: str
    workflow: str = "need_coordination"
    active_agent: str = "need"
    status: str = "active"
    stage: str = NeedWorkflowState.INITIATED.value
    sub_state: Optional[str] = None
    channel_metadata: Optional[Dict[str, Any]] = None

    # Resolution context
    coordinator_resolution: Optional[CoordinatorResolutionStatus] = None
    school_resolution: Optional[SchoolResolutionStatus] = None
    
    # Linked entities
    coordinator_id: Optional[str] = None
    school_id: Optional[str] = None
    need_draft_id: Optional[str] = None


class NeedAgentTurnRequest(BaseModel):
    """Request to process a turn in need conversation."""
    session_id: UUID
    session_state: NeedSessionState
    user_message: str
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    channel_metadata: Optional[Dict[str, Any]] = None


class NeedAgentTurnResponse(BaseModel):
    """Response from need agent turn."""
    assistant_message: str
    active_agent: str = "need"
    workflow: str = "need_coordination"
    state: str
    sub_state: Optional[str] = None
    completion_status: Optional[str] = None

    # Flat dict of all captured data — read by orchestrator to build journey_progress.
    # Keys: coordinator_name, school_name, subjects, grade_levels, student_count,
    #       time_slots, start_date, duration_weeks, completion_percentage.
    confirmed_fields: Dict[str, Any] = Field(default_factory=dict)

    # Resolution results (richer objects for internal use)
    coordinator_resolved: Optional[Coordinator] = None
    school_resolved: Optional[School] = None
    need_draft: Optional[NeedDraft] = None

    # Progress tracking
    missing_fields: List[str] = Field(default_factory=list)
    completion_percentage: int = 0

    # Events
    telemetry_events: List[Dict[str, Any]] = Field(default_factory=list)
    handoff_event: Optional[Dict[str, Any]] = None


# ============ MCP Tool Contracts ============

class CoordinatorResolutionResult(BaseModel):
    """Result of coordinator identity resolution."""
    status: CoordinatorResolutionStatus
    coordinator: Optional[Coordinator] = None
    linked_schools: List[School] = Field(default_factory=list)
    resolution_confidence: float = 0.0
    needs_verification: bool = False
    ambiguity_reason: Optional[str] = None


class SchoolResolutionResult(BaseModel):
    """Result of school context resolution."""
    status: SchoolResolutionStatus
    school: Optional[School] = None
    previous_needs: List[Dict[str, Any]] = Field(default_factory=list)
    needs_creation: bool = False
    ambiguity_reason: Optional[str] = None


class NeedSubmissionReadiness(BaseModel):
    """Evaluation of need submission readiness."""
    is_ready: bool
    missing_mandatory_fields: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    completion_percentage: int = 0
    recommendation: str = "continue_drafting"


class FulfillmentHandoffPayload(BaseModel):
    """Payload for handoff to fulfillment agent."""
    need_id: str
    school: School
    coordinator: Coordinator
    need_details: NeedDraft
    approval_status: str
    priority: str = "normal"
    notes: Optional[str] = None


# ============ Field Definitions ============

MANDATORY_NEED_FIELDS = [
    "subjects",
    "grade_levels",
    "student_count",
    "schedule_preference",
]

OPTIONAL_NEED_FIELDS = [
    "time_slots",
    "duration_weeks",
    "special_requirements",
]

SUBJECT_OPTIONS = [
    "mathematics",
    "science",
    "english",
    "hindi",
    "social_studies",
    "computer_basics",
    "spoken_english",
    "art",
    "music"
]

GRADE_LEVEL_OPTIONS = [
    "1", "2", "3", "4", "5",
    "6", "7", "8", "9", "10",
    "11", "12"
]
