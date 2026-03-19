"""
SERVE Orchestrator - Interaction Contracts
Defines the structured contract for inter-service communication.

This module provides clean, validated contracts that enforce
proper data flow between the Orchestrator and other services.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from uuid import UUID
from enum import Enum


# ============ Routing Contracts ============

class RoutingDecision(BaseModel):
    """
    Represents a routing decision made by the orchestrator.
    Captures which agent should handle the current request and why.
    """
    target_agent: str
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    reason: str
    fallback_agent: Optional[str] = None
    routing_context: Dict[str, Any] = Field(default_factory=dict)
    
    @field_validator('target_agent')
    @classmethod
    def validate_agent(cls, v: str) -> str:
        valid_agents = {'onboarding', 'selection', 'engagement', 'need', 'fulfillment', 'delivery_assistant'}
        if v not in valid_agents:
            raise ValueError(f"Invalid agent: {v}. Must be one of {valid_agents}")
        return v


class TransitionValidation(BaseModel):
    """
    Represents the result of validating a state transition.
    """
    is_valid: bool
    from_state: str
    to_state: str
    reason: str
    warnings: List[str] = Field(default_factory=list)
    required_fields_met: bool = True
    recommended_action: Optional[str] = None


# ============ Agent Invocation Contract ============

class AgentInvocationContext(BaseModel):
    """
    Complete context package sent to an agent for processing.
    This is the standardized contract for agent invocations.
    """
    session_id: UUID
    workflow: str
    current_stage: str
    active_agent: str
    user_message: str
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    volunteer_profile: Optional[Dict[str, Any]] = None
    confirmed_fields: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    context_summary: Optional[str] = None
    routing_metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentInvocationResult(BaseModel):
    """
    Standardized result from an agent invocation.
    """
    success: bool
    assistant_message: str
    new_state: str
    sub_state: Optional[str] = None
    extracted_fields: Dict[str, Any] = Field(default_factory=dict)
    completion_status: Literal['in_progress', 'complete', 'paused', 'error'] = 'in_progress'
    handoff_requested: bool = False
    handoff_target: Optional[str] = None
    handoff_reason: Optional[str] = None
    telemetry: List[Dict[str, Any]] = Field(default_factory=list)
    processing_time_ms: Optional[float] = None
    error_message: Optional[str] = None


# ============ Workflow Definition Contract ============

class WorkflowStageDefinition(BaseModel):
    """
    Defines a stage within a workflow, including valid transitions
    and the agent responsible for handling it.
    """
    stage_id: str
    display_name: str
    responsible_agent: str
    valid_next_stages: List[str]
    required_fields: List[str] = Field(default_factory=list)
    optional_fields: List[str] = Field(default_factory=list)
    can_pause: bool = True
    can_skip: bool = False
    timeout_minutes: Optional[int] = None


class WorkflowDefinition(BaseModel):
    """
    Complete workflow definition with all stages and transitions.
    """
    workflow_id: str
    display_name: str
    description: str
    initial_stage: str
    terminal_stages: List[str]
    stages: Dict[str, WorkflowStageDefinition]
    
    def get_stage(self, stage_id: str) -> Optional[WorkflowStageDefinition]:
        return self.stages.get(stage_id)
    
    def is_terminal(self, stage_id: str) -> bool:
        return stage_id in self.terminal_stages
    
    def can_transition(self, from_stage: str, to_stage: str) -> bool:
        stage = self.stages.get(from_stage)
        if not stage:
            return False
        return to_stage in stage.valid_next_stages


# ============ Session Context Contract ============

class SessionContext(BaseModel):
    """
    Complete session context used throughout orchestration.
    This is the source of truth for the current session state.
    """
    session_id: UUID
    channel: str
    persona: str
    workflow: str
    active_agent: str
    status: str
    current_stage: str
    sub_state: Optional[str] = None
    context_summary: Optional[str] = None
    volunteer_profile: Optional[Dict[str, Any]] = None
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    confirmed_fields: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def is_active(self) -> bool:
        return self.status == 'active'
    
    def is_complete(self) -> bool:
        return self.status == 'completed'


# ============ Orchestration Event Contracts ============

class OrchestrationEventType(str, Enum):
    SESSION_CREATED = 'session_created'
    SESSION_RESUMED = 'session_resumed'
    MESSAGE_RECEIVED = 'message_received'
    PERSONA_RESOLVED = 'persona_resolved'
    INTENT_RESOLVED = 'intent_resolved'
    AGENT_INVOKED = 'agent_invoked'
    AGENT_RESPONDED = 'agent_responded'
    STATE_TRANSITION = 'state_transition'
    ROUTING_DECISION = 'routing_decision'
    HANDOFF_INITIATED = 'handoff_initiated'
    VALIDATION_FAILED = 'validation_failed'
    ERROR_OCCURRED = 'error_occurred'


class OrchestrationEvent(BaseModel):
    """
    Structured event for logging orchestration activities.
    """
    event_type: OrchestrationEventType
    session_id: UUID
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    agent: Optional[str] = None
    workflow: Optional[str] = None
    stage: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    duration_ms: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None
    
    def to_log_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary suitable for structured logging."""
        return {
            'event': self.event_type.value,
            'session_id': str(self.session_id),
            'timestamp': self.timestamp.isoformat(),
            'agent': self.agent,
            'workflow': self.workflow,
            'stage': self.stage,
            'success': self.success,
            'duration_ms': self.duration_ms,
            'error': self.error_message,
            **self.details
        }
