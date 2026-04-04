"""
SERVE Selection Agent Service - Schemas

Silent evaluation agent. No volunteer-facing conversation.
Receives a volunteer profile after onboarding, evaluates readiness,
and returns a recommendation: recommend | not_recommend | hold.
"""
from typing import Any, Dict, List, Optional
from uuid import UUID
from enum import Enum
from pydantic import BaseModel, Field


class SelectionOutcome(str, Enum):
    RECOMMEND = "recommend"
    NOT_RECOMMEND = "not_recommend"
    HOLD = "hold"


class VolunteerProfile(BaseModel):
    """Profile data received from onboarding handoff."""
    volunteer_id: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    interests: List[str] = Field(default_factory=list)
    availability: Optional[str] = None
    languages: List[str] = Field(default_factory=list)
    experience: Optional[str] = None


class SelectionEvaluateRequest(BaseModel):
    """Request to evaluate a volunteer after onboarding."""
    session_id: UUID
    volunteer_id: Optional[str] = None
    profile: VolunteerProfile
    onboarding_summary: Optional[str] = None
    key_facts: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SelectionEvaluateResponse(BaseModel):
    """Evaluation result — no volunteer-facing message."""
    session_id: UUID
    volunteer_id: Optional[str] = None
    outcome: SelectionOutcome
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    reason: str = ""
    flags: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    evaluation_details: Dict[str, Any] = Field(default_factory=dict)
