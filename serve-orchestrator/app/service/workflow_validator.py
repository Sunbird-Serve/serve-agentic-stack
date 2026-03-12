"""
SERVE Orchestrator - Workflow Validator
Handles validation of state transitions within workflows.

The WorkflowValidator ensures:
1. State transitions follow defined workflow rules
2. Required fields are collected before advancing
3. Invalid transitions are caught and logged
"""
import logging
from typing import Dict, List, Optional
from uuid import UUID

from app.schemas import OnboardingState, WorkflowType, SessionStatus
from app.schemas.contracts import (
    TransitionValidation, WorkflowDefinition, WorkflowStageDefinition,
    OrchestrationEvent, OrchestrationEventType
)

logger = logging.getLogger(__name__)


# ============ Workflow Definitions ============

# Define the New Volunteer Onboarding workflow
NEW_VOLUNTEER_ONBOARDING_WORKFLOW = WorkflowDefinition(
    workflow_id='new_volunteer_onboarding',
    display_name='New Volunteer Onboarding',
    description='Guides new volunteers through the onboarding process to collect profile information',
    initial_stage='init',
    terminal_stages=['onboarding_complete'],
    stages={
        'init': WorkflowStageDefinition(
            stage_id='init',
            display_name='Welcome',
            responsible_agent='onboarding',
            valid_next_stages=['intent_discovery'],
            required_fields=[],
            can_pause=False,
            can_skip=False
        ),
        'intent_discovery': WorkflowStageDefinition(
            stage_id='intent_discovery',
            display_name='Understanding Your Interest',
            responsible_agent='onboarding',
            valid_next_stages=['purpose_orientation', 'paused'],
            required_fields=[],
            optional_fields=['motivation', 'interests'],
            can_pause=True
        ),
        'purpose_orientation': WorkflowStageDefinition(
            stage_id='purpose_orientation',
            display_name='About Our Mission',
            responsible_agent='onboarding',
            valid_next_stages=['eligibility_confirmation', 'paused'],
            required_fields=[],
            can_pause=True
        ),
        'eligibility_confirmation': WorkflowStageDefinition(
            stage_id='eligibility_confirmation',
            display_name='Getting to Know You',
            responsible_agent='onboarding',
            valid_next_stages=['capability_discovery', 'paused'],
            required_fields=['full_name', 'email'],
            optional_fields=['phone', 'location'],
            can_pause=True
        ),
        'capability_discovery': WorkflowStageDefinition(
            stage_id='capability_discovery',
            display_name='Your Skills & Availability',
            responsible_agent='onboarding',
            valid_next_stages=['profile_confirmation', 'paused'],
            required_fields=['skills', 'availability'],
            optional_fields=['experience_level', 'preferred_causes'],
            can_pause=True
        ),
        'profile_confirmation': WorkflowStageDefinition(
            stage_id='profile_confirmation',
            display_name='Confirm Your Profile',
            responsible_agent='onboarding',
            valid_next_stages=['onboarding_complete', 'capability_discovery', 'paused'],
            required_fields=['full_name', 'email', 'skills', 'availability'],
            can_pause=True
        ),
        'onboarding_complete': WorkflowStageDefinition(
            stage_id='onboarding_complete',
            display_name='Welcome Aboard!',
            responsible_agent='onboarding',
            valid_next_stages=[],  # Terminal state
            required_fields=['full_name', 'email', 'skills', 'availability'],
            can_pause=False,
            can_skip=False
        ),
        'paused': WorkflowStageDefinition(
            stage_id='paused',
            display_name='Paused',
            responsible_agent='onboarding',
            # Can resume to any active stage
            valid_next_stages=['init', 'intent_discovery', 'purpose_orientation',
                              'eligibility_confirmation', 'capability_discovery',
                              'profile_confirmation'],
            required_fields=[],
            can_pause=False  # Already paused
        )
    }
)


# Registry of all workflows
WORKFLOW_REGISTRY: Dict[str, WorkflowDefinition] = {
    'new_volunteer_onboarding': NEW_VOLUNTEER_ONBOARDING_WORKFLOW,
}


class WorkflowValidator:
    """
    Validates workflow state transitions and ensures data integrity.
    
    Responsibilities:
    - Validate state transitions against workflow definitions
    - Check required fields before advancing stages
    - Provide detailed validation feedback
    - Log validation events for debugging
    """
    
    def __init__(self):
        self.workflows = WORKFLOW_REGISTRY
    
    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """Get a workflow definition by ID."""
        return self.workflows.get(workflow_id)
    
    def validate_transition(
        self,
        workflow_id: str,
        from_state: str,
        to_state: str,
        confirmed_fields: Dict = None,
        session_id: UUID = None
    ) -> TransitionValidation:
        """
        Validate a state transition within a workflow.
        
        Args:
            workflow_id: The workflow being executed
            from_state: Current state
            to_state: Proposed next state
            confirmed_fields: Currently confirmed volunteer fields
            session_id: Session ID for logging
            
        Returns:
            TransitionValidation with validation result
        """
        confirmed_fields = confirmed_fields or {}
        workflow = self.get_workflow(workflow_id)
        
        if not workflow:
            return TransitionValidation(
                is_valid=False,
                from_state=from_state,
                to_state=to_state,
                reason=f"Unknown workflow: {workflow_id}",
                recommended_action="Check workflow configuration"
            )
        
        # Get current stage definition
        current_stage = workflow.get_stage(from_state)
        if not current_stage:
            return TransitionValidation(
                is_valid=False,
                from_state=from_state,
                to_state=to_state,
                reason=f"Unknown stage: {from_state}",
                recommended_action="Check stage configuration"
            )
        
        # Check if transition is allowed
        if to_state not in current_stage.valid_next_stages:
            # Special case: allow staying in same state
            if from_state == to_state:
                return TransitionValidation(
                    is_valid=True,
                    from_state=from_state,
                    to_state=to_state,
                    reason="Remaining in current stage",
                    warnings=["No state progression"]
                )
            
            return TransitionValidation(
                is_valid=False,
                from_state=from_state,
                to_state=to_state,
                reason=f"Transition from '{from_state}' to '{to_state}' is not allowed",
                recommended_action=f"Valid next stages: {current_stage.valid_next_stages}"
            )
        
        # Check required fields for the target stage
        target_stage = workflow.get_stage(to_state)
        if target_stage:
            missing_required = []
            for field in target_stage.required_fields:
                value = confirmed_fields.get(field)
                if not value or (isinstance(value, list) and len(value) == 0):
                    missing_required.append(field)
            
            if missing_required and to_state != 'paused':
                # Warning but allow - agent will collect missing fields
                warnings = [f"Missing fields for {to_state}: {missing_required}"]
                return TransitionValidation(
                    is_valid=True,
                    from_state=from_state,
                    to_state=to_state,
                    reason=f"Transition allowed with warnings",
                    warnings=warnings,
                    required_fields_met=False,
                    recommended_action="Collect missing required fields"
                )
        
        # Valid transition with all requirements met
        return TransitionValidation(
            is_valid=True,
            from_state=from_state,
            to_state=to_state,
            reason=f"Valid transition from '{from_state}' to '{to_state}'",
            required_fields_met=True
        )
    
    def get_missing_required_fields(
        self,
        workflow_id: str,
        stage: str,
        confirmed_fields: Dict
    ) -> List[str]:
        """
        Get list of required fields missing for a given stage.
        """
        workflow = self.get_workflow(workflow_id)
        if not workflow:
            return []
        
        stage_def = workflow.get_stage(stage)
        if not stage_def:
            return []
        
        missing = []
        for field in stage_def.required_fields:
            value = confirmed_fields.get(field)
            if not value or (isinstance(value, list) and len(value) == 0):
                missing.append(field)
        
        return missing
    
    def is_terminal_stage(self, workflow_id: str, stage: str) -> bool:
        """Check if a stage is a terminal (final) stage."""
        workflow = self.get_workflow(workflow_id)
        if not workflow:
            return False
        return workflow.is_terminal(stage)
    
    def get_completion_percentage(
        self,
        workflow_id: str,
        current_stage: str
    ) -> int:
        """
        Calculate workflow completion percentage based on current stage.
        """
        workflow = self.get_workflow(workflow_id)
        if not workflow:
            return 0
        
        # Define stage order for progress calculation
        stage_order = [
            'init', 'intent_discovery', 'purpose_orientation',
            'eligibility_confirmation', 'capability_discovery',
            'profile_confirmation', 'onboarding_complete'
        ]
        
        if current_stage not in stage_order:
            return 0
        
        current_index = stage_order.index(current_stage)
        total_stages = len(stage_order) - 1  # Exclude terminal
        
        return round((current_index / total_stages) * 100) if total_stages > 0 else 0
    
    def log_validation_event(
        self,
        session_id: UUID,
        validation: TransitionValidation,
        workflow_id: str
    ) -> OrchestrationEvent:
        """
        Create a structured log event for validation results.
        """
        event = OrchestrationEvent(
            event_type=OrchestrationEventType.STATE_TRANSITION if validation.is_valid 
                       else OrchestrationEventType.VALIDATION_FAILED,
            session_id=session_id,
            workflow=workflow_id,
            stage=validation.to_state,
            success=validation.is_valid,
            details={
                'from_state': validation.from_state,
                'to_state': validation.to_state,
                'reason': validation.reason,
                'warnings': validation.warnings,
                'required_fields_met': validation.required_fields_met,
                'recommended_action': validation.recommended_action
            }
        )
        
        log_level = logging.INFO if validation.is_valid else logging.WARNING
        logger.log(log_level, f"Validation: {event.to_log_dict()}")
        
        return event


# Singleton instance
workflow_validator = WorkflowValidator()
