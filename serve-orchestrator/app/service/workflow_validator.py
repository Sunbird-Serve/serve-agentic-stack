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


# Define the Need Coordination workflow
NEED_COORDINATION_WORKFLOW = WorkflowDefinition(
    workflow_id='need_coordination',
    display_name='Need Coordination',
    description='Guides need coordinators through capturing and validating school needs',
    initial_stage='initiated',
    terminal_stages=['approved', 'rejected', 'fulfillment_handoff_ready'],
    stages={
        'initiated': WorkflowStageDefinition(
            stage_id='initiated',
            display_name='Welcome',
            responsible_agent='need',
            valid_next_stages=['resolving_coordinator', 'paused'],
            required_fields=[],
            can_pause=True
        ),
        'resolving_coordinator': WorkflowStageDefinition(
            stage_id='resolving_coordinator',
            display_name='Identifying You',
            responsible_agent='need',
            valid_next_stages=['resolving_school', 'human_review', 'paused'],
            required_fields=[],
            optional_fields=['coordinator_name', 'whatsapp_number'],
            can_pause=True
        ),
        'resolving_school': WorkflowStageDefinition(
            stage_id='resolving_school',
            display_name='Your School',
            responsible_agent='need',
            valid_next_stages=['drafting_need', 'human_review', 'paused'],
            required_fields=[],
            optional_fields=['school_name', 'school_location'],
            can_pause=True
        ),
        'drafting_need': WorkflowStageDefinition(
            stage_id='drafting_need',
            display_name='Capturing Your Need',
            responsible_agent='need',
            valid_next_stages=['pending_approval', 'paused'],
            required_fields=['subjects', 'grade_levels', 'student_count', 'time_slots', 'start_date', 'duration_weeks'],
            optional_fields=['schedule_preference', 'special_requirements'],
            can_pause=True
        ),
        'pending_approval': WorkflowStageDefinition(
            stage_id='pending_approval',
            display_name='Review & Confirm',
            responsible_agent='need',
            valid_next_stages=['approved', 'refinement_required', 'drafting_need', 'rejected', 'paused'],
            required_fields=['subjects', 'grade_levels', 'student_count', 'time_slots', 'start_date', 'duration_weeks'],
            can_pause=True
        ),
        'refinement_required': WorkflowStageDefinition(
            stage_id='refinement_required',
            display_name='Updates Needed',
            responsible_agent='need',
            valid_next_stages=['drafting_need', 'pending_approval', 'paused'],
            required_fields=[],
            can_pause=True
        ),
        'approved': WorkflowStageDefinition(
            stage_id='approved',
            display_name='Need Confirmed',
            responsible_agent='need',
            valid_next_stages=['fulfillment_handoff_ready'],
            required_fields=['subjects', 'grade_levels', 'student_count', 'time_slots', 'start_date', 'duration_weeks'],
            can_pause=False
        ),
        'fulfillment_handoff_ready': WorkflowStageDefinition(
            stage_id='fulfillment_handoff_ready',
            display_name='Ready for Matching',
            responsible_agent='need',
            valid_next_stages=[],  # Terminal - handoff to fulfillment agent
            required_fields=[],
            can_pause=False
        ),
        'human_review': WorkflowStageDefinition(
            stage_id='human_review',
            display_name='Under Review',
            responsible_agent='need',
            valid_next_stages=['resolving_coordinator', 'resolving_school', 'drafting_need', 'rejected'],
            required_fields=[],
            can_pause=False
        ),
        'paused': WorkflowStageDefinition(
            stage_id='paused',
            display_name='Paused',
            responsible_agent='need',
            valid_next_stages=['initiated', 'resolving_coordinator', 'resolving_school',
                              'drafting_need', 'pending_approval', 'refinement_required'],
            required_fields=[],
            can_pause=False
        ),
        'rejected': WorkflowStageDefinition(
            stage_id='rejected',
            display_name='Not Approved',
            responsible_agent='need',
            valid_next_stages=[],  # Terminal
            required_fields=[],
            can_pause=False
        )
    }
)


# Define the Returning Volunteer Engagement workflow
RETURNING_VOLUNTEER_WORKFLOW = WorkflowDefinition(
    workflow_id='returning_volunteer',
    display_name='Returning Volunteer Re-engagement',
    description='Re-engages returning volunteers, refreshes their profile, and prepares them for matching',
    initial_stage='re_engaging',
    terminal_stages=['matching_ready'],
    stages={
        're_engaging': WorkflowStageDefinition(
            stage_id='re_engaging',
            display_name='Welcome Back',
            responsible_agent='engagement',
            valid_next_stages=['profile_refresh', 'paused'],
            required_fields=[],
            can_pause=True,
        ),
        'profile_refresh': WorkflowStageDefinition(
            stage_id='profile_refresh',
            display_name='Update Your Profile',
            responsible_agent='engagement',
            valid_next_stages=['matching_ready', 'paused'],
            required_fields=['availability'],
            optional_fields=['skills', 'interests', 'preferred_causes'],
            can_pause=True,
        ),
        'matching_ready': WorkflowStageDefinition(
            stage_id='matching_ready',
            display_name='Ready for Matching',
            responsible_agent='engagement',
            valid_next_stages=[],  # Terminal — hand off to selection agent
            required_fields=['availability'],
            can_pause=False,
            can_skip=False,
        ),
        'paused': WorkflowStageDefinition(
            stage_id='paused',
            display_name='Paused',
            responsible_agent='engagement',
            valid_next_stages=['re_engaging', 'profile_refresh'],
            required_fields=[],
            can_pause=False,
        ),
    }
)


# Registry of all workflows
WORKFLOW_REGISTRY: Dict[str, WorkflowDefinition] = {
    'new_volunteer_onboarding': NEW_VOLUNTEER_ONBOARDING_WORKFLOW,
    'need_coordination': NEED_COORDINATION_WORKFLOW,
    'returning_volunteer': RETURNING_VOLUNTEER_WORKFLOW,
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
        
        # Define stage order for progress calculation by workflow
        stage_orders = {
            'new_volunteer_onboarding': [
                'init', 'intent_discovery', 'purpose_orientation',
                'eligibility_confirmation', 'capability_discovery',
                'profile_confirmation', 'onboarding_complete'
            ],
            'need_coordination': [
                'initiated', 'resolving_coordinator', 'resolving_school',
                'drafting_need', 'pending_approval', 'approved',
                'fulfillment_handoff_ready'
            ],
            'returning_volunteer': [
                're_engaging', 'profile_refresh', 'matching_ready'
            ],
        }
        
        stage_order = stage_orders.get(workflow_id, [])
        
        if current_stage not in stage_order:
            # Handle special states
            if current_stage in ['paused', 'human_review', 'refinement_required']:
                return 50  # Midway indicator
            if current_stage in ['rejected']:
                return 100  # Terminal
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
