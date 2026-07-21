"""
SERVE MCP Server - Tool Input Schemas
Pydantic models for all MCP tool inputs.
FastMCP uses these to generate precise JSON schemas for the LLM,
and to validate inputs before they reach service code.
"""
from typing import Any, ClassVar, Dict, List, Literal, Optional, Set
from pydantic import BaseModel, Field, field_validator, model_validator
import re


# ─── Shared validators ────────────────────────────────────────────────────────

def _non_empty(v: str, field_name: str = "field") -> str:
    if not v or not v.strip():
        raise ValueError(f"{field_name} must not be empty")
    return v.strip()


_NAME_WORD_PATTERN = re.compile(r"^[A-Za-z]+(?:['\-][A-Za-z]+)*$")


def _is_valid_full_name(value: str) -> bool:
    """
    Defense-in-depth check at the MCP boundary: a valid full name has a first
    and last name, each 2-20 letters (hyphen/apostrophe allowed). This mirrors
    the onboarding agent's own check, duplicated here so no caller — current
    or future, from any service — can persist an unvalidated name by bypassing
    the onboarding agent's client-side logic.
    """
    words = value.split()
    if len(words) < 2 or len(value) > 60:
        return False
    for word in words:
        if not (2 <= len(word) <= 20):
            return False
        if not _NAME_WORD_PATTERN.match(word):
            return False
    return True


# ─── Identity ────────────────────────────────────────────────────────────────

class LookupActorInput(BaseModel):
    actor_id: str = Field(
        description="Channel-native identity: email address, phone number (+91…), or temp session UUID"
    )
    channel: Literal["web_ui", "whatsapp", "api", "mobile", "scheduler"] = Field(
        description="Channel the actor is using"
    )
    identity_type: Optional[Literal["email", "phone", "session_id", "system"]] = Field(
        default=None,
        description="Identity type (inferred from actor_id if omitted)"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Existing MCP session UUID to link the resolution log to"
    )


# ─── Session ─────────────────────────────────────────────────────────────────

class StartSessionInput(BaseModel):
    channel: Literal["web_ui", "whatsapp", "api", "scheduler", "mobile"] = Field(
        default="web_ui"
    )
    persona: Literal[
        "new_volunteer", "returning_volunteer", "recommended_volunteer",
        "inactive_volunteer", "need_coordinator", "system"
    ] = Field(default="new_volunteer")
    channel_metadata: Optional[Dict[str, Any]] = Field(default=None)
    actor_id: Optional[str] = Field(
        default=None,
        description="Channel-native identity from lookup_actor result"
    )
    identity_type: Optional[Literal["email", "phone", "session_id", "system", "keycloak"]] = Field(
        default=None
    )
    user_type: Optional[Literal[
        "new_user", "registry_known", "returning_ai_user", "coordinator", "anonymous"
    ]] = Field(default=None)
    volunteer_id: Optional[str] = Field(
        default=None,
        description="Serve Registry osid from lookup_actor serve_entity_id"
    )
    coordinator_id: Optional[str] = Field(
        default=None,
        description="Serve Registry coordinator osid"
    )
    idempotency_key: Optional[str] = Field(
        default=None,
        description="Deduplication key — WhatsApp wamid or similar"
    )


class GetSessionInput(BaseModel):
    session_id: str = Field(description="UUID of the session")

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"session_id must be a valid UUID, got: {v}")
        return v


class ResumeSessionInput(BaseModel):
    session_id: str = Field(description="UUID of the session to resume")

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"session_id must be a valid UUID, got: {v}")
        return v


class FindSessionByActorInput(BaseModel):
    actor_id: str = Field(description="Keycloak sub or other stable actor identifier")


class UpdateSessionActorInput(BaseModel):
    session_id: str = Field(description="UUID of the session to update")
    actor_id: str = Field(description="New actor_id (e.g., Keycloak sub) to link to this session")


class AdvanceSessionStateInput(BaseModel):
    session_id: str = Field(description="UUID of the session")
    new_state: str = Field(description="Target workflow stage")
    sub_state: Optional[str] = Field(default=None)
    active_agent: Optional[Literal[
        "onboarding", "selection", "engagement",
        "need", "fulfillment", "delivery_assistant"
    ]] = Field(default=None)

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"session_id must be a valid UUID, got: {v}")
        return v

    @field_validator("new_state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        return _non_empty(v, "new_state")


class ListSessionsInput(BaseModel):
    status: Optional[Literal["active", "paused", "completed", "abandoned", "escalated"]] = Field(
        default=None
    )
    limit: int = Field(default=50, ge=1, le=500)


# ─── Profile ─────────────────────────────────────────────────────────────────

class GetMissingFieldsInput(BaseModel):
    session_id: str

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"session_id must be a valid UUID, got: {v}")
        return v


_VOLUNTEER_ALLOWED_FIELDS: Set[str] = {
    "full_name", "first_name", "gender", "dob", "email", "phone",
    "location", "skills", "skill_levels", "interests", "languages",
    "availability", "days_preferred", "time_preferred",
    "qualification", "years_of_experience", "employment_status",
    "motivation", "experience_level", "eligibility_status",
}


class SaveVolunteerFieldsInput(BaseModel):
    session_id: str
    fields: Dict[str, Any] = Field(
        description=(
            "Supported keys: full_name, first_name, gender, dob, email, phone, "
            "location, skills (list), skill_levels (dict), interests (list), "
            "languages (list), availability, days_preferred (list), "
            "time_preferred (list), qualification, years_of_experience, "
            "employment_status, motivation, experience_level"
        )
    )

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, v: Dict) -> Dict:
        if not v:
            raise ValueError("fields must not be empty")
        unknown = set(v.keys()) - _VOLUNTEER_ALLOWED_FIELDS
        if unknown:
            raise ValueError(f"Unknown field(s): {unknown}. Allowed: {_VOLUNTEER_ALLOWED_FIELDS}")
        email = v.get("email")
        if email and "@" not in str(email):
            raise ValueError("email must be a valid email address")
        if "full_name" in v:
            full_name = str(v["full_name"] or "").strip()
            if not _is_valid_full_name(full_name):
                raise ValueError(
                    "full_name must contain a first and last name "
                    "(letters, hyphens, and apostrophes only)"
                )
        return v

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"session_id must be a valid UUID, got: {v}")
        return v


class EvaluateReadinessInput(BaseModel):
    session_id: str

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"session_id must be a valid UUID, got: {v}")
        return v


# ─── Conversation ─────────────────────────────────────────────────────────────

class SaveMessageInput(BaseModel):
    session_id: str
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)
    agent: Optional[Literal[
        "onboarding", "selection", "engagement",
        "need", "fulfillment", "delivery_assistant"
    ]] = Field(default=None)
    message_metadata: Optional[Dict[str, Any]] = Field(default=None)

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"session_id must be a valid UUID, got: {v}")
        return v


class GetConversationInput(BaseModel):
    session_id: str
    limit: int = Field(default=50, ge=1, le=200)

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"session_id must be a valid UUID, got: {v}")
        return v


# ─── Memory ───────────────────────────────────────────────────────────────────

class SaveMemorySummaryInput(BaseModel):
    session_id: str
    summary_text: str = Field(min_length=1)
    key_facts: Optional[List[str]] = Field(default=None)
    volunteer_id: Optional[str] = Field(default=None)

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"session_id must be a valid UUID, got: {v}")
        return v


class GetMemorySummaryInput(BaseModel):
    session_id: str

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"session_id must be a valid UUID, got: {v}")
        return v


# ─── Engagement Hybrid Tools ─────────────────────────────────────────────────

class EngagementSaveConfirmedSignalsInput(BaseModel):
    session_id: str
    signals: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"session_id must be a valid UUID, got: {v}")
        return v


class EngagementUpdateVolunteerStatusInput(BaseModel):
    session_id: str
    volunteer_status: Literal[
        "continue_nurturing",
        "opportunity_readiness",
        "pause_outreach",
        "opt_out",
        "human_review",
    ]
    reason: Optional[str] = Field(default=None)
    signals: Optional[Dict[str, Any]] = Field(default=None)

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"session_id must be a valid UUID, got: {v}")
        return v


class EngagementPrepareFulfillmentHandoffInput(BaseModel):
    session_id: str
    signals: Optional[Dict[str, Any]] = Field(default=None)

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"session_id must be a valid UUID, got: {v}")
        return v


# ─── Telemetry ────────────────────────────────────────────────────────────────

class LogEventInput(BaseModel):
    session_id: str
    event_type: str = Field(min_length=1)
    agent: Optional[str] = Field(default=None)
    data: Optional[Dict[str, Any]] = Field(default=None)
    domain: Optional[Literal["volunteer", "need", "system"]] = Field(default=None)
    source_service: Optional[Literal[
        "orchestrator", "onboarding_agent", "need_agent"
    ]] = Field(default=None)
    duration_ms: Optional[int] = Field(default=None, ge=0)

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"session_id must be a valid UUID, got: {v}")
        return v


class EmitHandoffEventInput(BaseModel):
    session_id: str
    from_agent: str = Field(min_length=1)
    to_agent: str = Field(min_length=1)
    handoff_type: Literal["agent_transition", "resume", "escalation", "pause"]
    payload: Optional[Dict[str, Any]] = Field(default=None)
    reason: Optional[str] = Field(default=None)

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"session_id must be a valid UUID, got: {v}")
        return v


# ─── Coordinator ──────────────────────────────────────────────────────────────

class ResolveCoordinatorInput(BaseModel):
    whatsapp_number: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)
    name: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def at_least_one(self) -> "ResolveCoordinatorInput":
        if not self.whatsapp_number and not self.email and not self.name:
            raise ValueError("At least one of whatsapp_number, email, or name must be provided")
        return self

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v and "@" not in v:
            raise ValueError("email must be a valid email address")
        return v


class CreateCoordinatorInput(BaseModel):
    name: str = Field(min_length=1)
    whatsapp_number: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v and "@" not in v:
            raise ValueError("email must be a valid email address")
        return v


class MapCoordinatorToSchoolInput(BaseModel):
    coordinator_id: str = Field(min_length=1, description="Serve Registry coordinator osid")
    school_id: str = Field(min_length=1, description="Serve Need Service entity UUID")


# ─── School ───────────────────────────────────────────────────────────────────

class ResolveSchoolContextInput(BaseModel):
    coordinator_id: Optional[str] = Field(default=None)
    school_hint: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def at_least_one(self) -> "ResolveSchoolContextInput":
        if not self.coordinator_id and not self.school_hint:
            raise ValueError("At least one of coordinator_id or school_hint must be provided")
        return self


class CreateSchoolContextInput(BaseModel):
    name: str = Field(min_length=1)
    location: str = Field(min_length=1)
    contact_number: Optional[str] = Field(default=None)
    coordinator_id: Optional[str] = Field(default=None)
    district: Optional[str] = Field(default=None)
    state: Optional[str] = Field(default=None)


class FetchPreviousNeedContextInput(BaseModel):
    school_id: str = Field(min_length=1, description="Serve Need Service entity UUID")


# ─── Need Draft ───────────────────────────────────────────────────────────────

class CreateOrUpdateNeedDraftInput(BaseModel):
    session_id: str
    subjects: Optional[List[str]] = Field(default=None)
    grade_levels: Optional[List[str]] = Field(default=None)
    student_count: Optional[int] = Field(default=None, ge=1, le=10000)
    time_slots: Optional[List[Any]] = Field(default=None)
    start_date: Optional[str] = Field(
        default=None,
        description="ISO date string (YYYY-MM-DD)"
    )
    duration_weeks: Optional[int] = Field(default=None, ge=1, le=52)
    schedule_preference: Optional[str] = Field(default=None)
    grade_schedule: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Per-grade schedule mapping: "
            "{\"6\": {\"days\": [\"Monday\",\"Tuesday\"], \"time_slot\": \"13:00-14:00\"}, ...}"
        )
    )
    skipped_grades: Optional[List[str]] = Field(
        default=None,
        description="Grades coordinator opted out of, e.g. [\"8\"]"
    )
    special_requirements: Optional[str] = Field(default=None)
    coordinator_osid: Optional[str] = Field(default=None)
    entity_id: Optional[str] = Field(default=None)

    @field_validator("session_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"session_id must be a valid UUID, got: {v}")
        return v

    @field_validator("start_date")
    @classmethod
    def validate_date(cls, v: Optional[str]) -> Optional[str]:
        if v:
            from datetime import date
            try:
                date.fromisoformat(v)
            except ValueError:
                raise ValueError(f"start_date must be ISO format YYYY-MM-DD, got: {v}")
        return v


class SubmitNeedInput(BaseModel):
    need_id: str = Field(min_length=1, description="MCP DB draft UUID")


class UpdateNeedStatusInput(BaseModel):
    need_id: str = Field(min_length=1)
    status: Literal[
        "draft", "pending_approval", "approved",
        "refinement_required", "paused", "rejected", "submitted"
    ]
    comments: Optional[str] = Field(default=None)


class PrepareHandoffInput(BaseModel):
    need_id: str = Field(min_length=1)


class PauseNeedSessionInput(BaseModel):
    session_id: str
    reason: Optional[str] = Field(default=None)


class SaveNeedMessageInput(BaseModel):
    session_id: str
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)
    agent: Optional[str] = Field(default=None)


class LogNeedEventInput(BaseModel):
    session_id: str
    event_type: str = Field(min_length=1)
    data: Optional[Dict[str, Any]] = Field(default=None)


class EmitNeedHandoffInput(BaseModel):
    session_id: str
    from_agent: str = Field(min_length=1)
    to_agent: str = Field(min_length=1)
    payload: Dict[str, Any]


# ─── Analytics ────────────────────────────────────────────────────────────────

class GetSessionAnalyticsInput(BaseModel):
    date_from: Optional[str] = Field(
        default=None,
        description="ISO date YYYY-MM-DD (defaults to last 30 days)"
    )
    date_to: Optional[str] = Field(
        default=None,
        description="ISO date YYYY-MM-DD (defaults to today)"
    )

    @field_validator("date_from", "date_to")
    @classmethod
    def validate_date(cls, v: Optional[str]) -> Optional[str]:
        if v:
            from datetime import date
            try:
                date.fromisoformat(v)
            except ValueError:
                raise ValueError(f"Date must be ISO format YYYY-MM-DD, got: {v}")
        return v


# ─── Engagement / Fulfillment — Volunteer History & Nominations ───────────────

class GetVolunteerFulfillmentHistoryInput(BaseModel):
    volunteer_id: str = Field(
        min_length=1,
        description="Serve Registry volunteer osid"
    )
    page: int = Field(default=0, ge=0)
    size: int = Field(default=50, ge=1, le=200)


class CheckActiveNominationsInput(BaseModel):
    volunteer_id: str = Field(
        min_length=1,
        description="Serve Registry volunteer osid"
    )


class GetEngagementContextInput(BaseModel):
    phone: str = Field(
        min_length=7,
        description="Volunteer's WhatsApp/mobile number — used to look up the volunteer and return fulfillment history + profile in one call"
    )


class GetEngagementContextByEmailInput(BaseModel):
    email: str = Field(
        min_length=3,
        description="Volunteer's email address — fallback when phone lookup fails"
    )


class GetNeedsForEntityInput(BaseModel):
    entity_id: str = Field(min_length=1, description="Serve Need Service entity / school UUID")
    page: int = Field(default=0, ge=0)
    size: int = Field(default=20, ge=1, le=200)


class GetNeedDetailsInput(BaseModel):
    need_id: str = Field(min_length=1, description="Serve Need Service need UUID")


class NominateVolunteerInput(BaseModel):
    need_id: str = Field(min_length=1, description="Serve Need Service need UUID")
    volunteer_id: str = Field(min_length=1, description="Serve Registry volunteer osid")


class ConfirmNominationInput(BaseModel):
    volunteer_id: str = Field(min_length=1, description="Serve Registry volunteer osid")
    nomination_id: str = Field(min_length=1, description="Nomination UUID")
    status: Literal["Nominated", "Approved", "Proposed", "Backfill", "Rejected"] = Field(
        description="New nomination status"
    )


class GetNominationsForNeedInput(BaseModel):
    need_id: str = Field(min_length=1, description="Serve Need Service need UUID")
    status: Optional[Literal["Nominated", "Approved", "Proposed", "Backfill", "Rejected"]] = Field(
        default=None,
        description="Filter by status (omit for all nominations)"
    )


class GetRecommendedVolunteersInput(BaseModel):
    already_nominated: bool = Field(
        default=False,
        description="False → recommendedNotNominated, True → recommendedNominated"
    )


# ─── Volunteer Fact-Store ──────────────────────────────────────────────────────

class FindVolunteerInput(BaseModel):
    """Find a volunteer by any known identifier."""
    email: Optional[str] = Field(None, description="Email address")
    phone: Optional[str] = Field(None, description="Phone number")
    serve_registry_id: Optional[str] = Field(None, description="Serve Registry osid")


class CreateVolunteerInput(BaseModel):
    """Create a new volunteer in the fact-store."""
    full_name: Optional[str] = Field(None, description="Volunteer's full name")
    phone: Optional[str] = Field(None, description="Phone number")
    email: Optional[str] = Field(None, description="Email address")
    serve_registry_id: Optional[str] = Field(None, description="Serve Registry osid")
    facts: Optional[Dict[str, Any]] = Field(None, description="Initial facts to store")


class MergeVolunteerFactsInput(BaseModel):
    """Merge new facts into a volunteer's existing fact-set."""
    volunteer_id: str = Field(description="Platform volunteer UUID")
    facts: Dict[str, Any] = Field(description="Facts to merge (shallow at top, deep for credentials/preferences/commitments)")


class GetVolunteerFactsInput(BaseModel):
    """Get the full fact-set for a volunteer."""
    volunteer_id: str = Field(description="Platform volunteer UUID")


class CheckVolunteerCredentialInput(BaseModel):
    """Check if a volunteer has a specific credential."""
    volunteer_id: str = Field(description="Platform volunteer UUID")
    category: str = Field(description="Credential category (e.g., english_teaching, hindi_teaching)")
    required_status: str = Field(default="recommended", description="Required status to pass the check")
