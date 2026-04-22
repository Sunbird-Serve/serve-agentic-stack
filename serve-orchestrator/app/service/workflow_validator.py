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
    description='Welcomes new volunteers, runs eligibility checks, registers them, then moves through selection and engagement',
    initial_stage='welcome',
    terminal_stages=['complete', 'human_review'],
    stages={
        'welcome': WorkflowStageDefinition(
            stage_id='welcome',
            display_name='Welcome',
            responsible_agent='onboarding',
            valid_next_stages=['orientation_video'],
            required_fields=[],
            can_pause=False,
            can_skip=False
        ),
        'orientation_video': WorkflowStageDefinition(
            stage_id='orientation_video',
            display_name='Orientation Video',
            responsible_agent='onboarding',
            valid_next_stages=['eligibility_screening', 'paused'],
            required_fields=[],
            can_pause=True
        ),
        'eligibility_screening': WorkflowStageDefinition(
            stage_id='eligibility_screening',
            display_name='Eligibility Check',
            responsible_agent='onboarding',
            valid_next_stages=['contact_capture', 'human_review', 'paused'],
            required_fields=[],
            can_pause=True
        ),
        'contact_capture': WorkflowStageDefinition(
            stage_id='contact_capture',
            display_name='Contact Details',
            responsible_agent='onboarding',
            valid_next_stages=['registration_review', 'paused'],
            required_fields=['full_name', 'phone', 'email'],
            optional_fields=['location'],
            can_pause=True
        ),
        'teaching_profile': WorkflowStageDefinition(
            stage_id='teaching_profile',
            display_name='Legacy Teaching Profile',
            responsible_agent='onboarding',
            valid_next_stages=['registration_review', 'paused'],
            required_fields=[],
            optional_fields=['skills', 'availability', 'languages', 'interests'],
            can_pause=True
        ),
        'registration_review': WorkflowStageDefinition(
            stage_id='registration_review',
            display_name='Confirm Details',
            responsible_agent='onboarding',
            valid_next_stages=['onboarding_complete', 'contact_capture', 'human_review', 'paused'],
            required_fields=['full_name', 'phone', 'email'],
            can_pause=True
        ),
        'onboarding_complete': WorkflowStageDefinition(
            stage_id='onboarding_complete',
            display_name='Registration Complete',
            responsible_agent='selection',
            valid_next_stages=['selection_conversation'],
            required_fields=['full_name', 'phone', 'email'],
            can_pause=False,
            can_skip=False
        ),
        'selection_conversation': WorkflowStageDefinition(
            stage_id='selection_conversation',
            display_name='Selection Conversation',
            responsible_agent='selection',
            valid_next_stages=['gathering_preferences', 'human_review', 'paused'],
            required_fields=[],
            can_pause=True
        ),
        'gathering_preferences': WorkflowStageDefinition(
            stage_id='gathering_preferences',
            display_name='Engagement Preferences',
            responsible_agent='engagement',
            valid_next_stages=['active', 'paused', 'human_review'],
            required_fields=[],
            can_pause=True
        ),
        'active': WorkflowStageDefinition(
            stage_id='active',
            display_name='Fulfillment Active',
            responsible_agent='fulfillment',
            valid_next_stages=['complete', 'human_review', 'paused'],
            required_fields=[],
            can_pause=True
        ),
        'complete': WorkflowStageDefinition(
            stage_id='complete',
            display_name='Completed',
            responsible_agent='fulfillment',
            valid_next_stages=[],
            required_fields=[],
            can_pause=False
        ),
        'human_review': WorkflowStageDefinition(
            stage_id='human_review',
            display_name='Review Pending',
            responsible_agent='selection',
            valid_next_stages=[],
            required_fields=[],
            can_pause=False,
            can_skip=False
        ),
        'paused': WorkflowStageDefinition(
            stage_id='paused',
            display_name='Paused',
            responsible_agent='onboarding',
            # Can resume to any active stage
            valid_next_stages=['welcome', 'orientation_video', 'eligibility_screening',
                              'contact_capture', 'registration_review',
                              'selection_conversation', 'gathering_preferences', 'active'],
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
    terminal_stages=['submitted', 'approved', 'rejected', 'fulfillment_handoff_ready'],
    stages={
        'initiated': WorkflowStageDefinition(
            stage_id='initiated',
            display_name='Welcome',
            responsible_agent='need',
            valid_next_stages=['capturing_phone', 'resolving_coordinator', 'confirming_identity', 'drafting_need', 'paused'],
            required_fields=[],
            can_pause=True
        ),
        'capturing_phone': WorkflowStageDefinition(
            stage_id='capturing_phone',
            display_name='Phone Number',
            responsible_agent='need',
            valid_next_stages=['resolving_coordinator', 'paused'],
            required_fields=[],
            can_pause=True
        ),
        'resolving_coordinator': WorkflowStageDefinition(
            stage_id='resolving_coordinator',
            display_name='Identifying You',
            responsible_agent='need',
            valid_next_stages=['resolving_school', 'confirming_identity', 'drafting_need', 'human_review', 'paused'],
            required_fields=[],
            optional_fields=['coordinator_name', 'whatsapp_number'],
            can_pause=True
        ),
        'confirming_identity': WorkflowStageDefinition(
            stage_id='confirming_identity',
            display_name='Confirm Your Details',
            responsible_agent='need',
            valid_next_stages=['drafting_need', 'resolving_coordinator', 'paused'],
            required_fields=[],
            can_pause=True
        ),
        'resolving_school': WorkflowStageDefinition(
            stage_id='resolving_school',
            display_name='Your School',
            responsible_agent='need',
            valid_next_stages=['confirming_identity', 'drafting_need', 'human_review', 'paused'],
            required_fields=[],
            optional_fields=['school_name', 'school_location'],
            can_pause=True
        ),
        'drafting_need': WorkflowStageDefinition(
            stage_id='drafting_need',
            display_name='Capturing Your Need',
            responsible_agent='need',
            valid_next_stages=['pending_approval', 'paused'],
            required_fields=['subjects', 'grade_levels', 'student_count', 'schedule_preference'],
            optional_fields=['time_slots', 'duration_weeks', 'special_requirements', 'start_date'],
            can_pause=True
        ),
        'pending_approval': WorkflowStageDefinition(
            stage_id='pending_approval',
            display_name='Review & Confirm',
            responsible_agent='need',
            valid_next_stages=['submitted', 'approved', 'refinement_required', 'drafting_need', 'rejected', 'paused'],
            required_fields=['subjects', 'grade_levels', 'student_count', 'schedule_preference', 'start_date'],
            can_pause=True
        ),
        'submitted': WorkflowStageDefinition(
            stage_id='submitted',
            display_name='Need Registered',
            responsible_agent='need',
            valid_next_stages=['fulfillment_handoff_ready', 'refinement_required', 'drafting_need'],
            required_fields=[],
            can_pause=False
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
            valid_next_stages=['initiated', 'capturing_phone', 'resolving_coordinator',
                              'confirming_identity', 'resolving_school', 'drafting_need', 'pending_approval',
                              'refinement_required'],
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
    description='Re-engages returning volunteers, captures continuity preferences, and hands ready volunteers to fulfillment',
    initial_stage='re_engaging',
    terminal_stages=['complete', 'human_review'],
    stages={
        're_engaging': WorkflowStageDefinition(
            stage_id='re_engaging',
            display_name='Welcome Back',
            responsible_agent='engagement',
            valid_next_stages=['profile_refresh', 'matching_ready', 'active', 'paused', 'human_review'],
            required_fields=[],
            can_pause=True,
        ),
        'profile_refresh': WorkflowStageDefinition(
            stage_id='profile_refresh',
            display_name='Confirm Continuation Preferences',
            responsible_agent='engagement',
            valid_next_stages=['matching_ready', 'active', 'paused', 'human_review'],
            required_fields=[],
            optional_fields=['same_school', 'same_slot', 'continuity'],
            can_pause=True,
        ),
        'matching_ready': WorkflowStageDefinition(
            stage_id='matching_ready',
            display_name='Ready For Fulfillment',
            responsible_agent='engagement',
            valid_next_stages=['active', 'paused', 'human_review'],
            required_fields=[],
            can_pause=False,
            can_skip=False,
        ),
        'active': WorkflowStageDefinition(
            stage_id='active',
            display_name='Matching In Progress',
            responsible_agent='fulfillment',
            valid_next_stages=['complete', 'human_review', 'paused'],
            required_fields=[],
            can_pause=True,
        ),
        'complete': WorkflowStageDefinition(
            stage_id='complete',
            display_name='Matched',
            responsible_agent='fulfillment',
            valid_next_stages=[],
            required_fields=[],
            can_pause=False,
        ),
        'human_review': WorkflowStageDefinition(
            stage_id='human_review',
            display_name='Needs Human Follow-up',
            responsible_agent='engagement',
            valid_next_stages=[],
            required_fields=[],
            can_pause=False,
        ),
        'paused': WorkflowStageDefinition(
            stage_id='paused',
            display_name='Paused',
            responsible_agent='engagement',
            valid_next_stages=['re_engaging', 'profile_refresh', 'active'],
            required_fields=[],
            can_pause=False,
        ),
    }
)


# Define the Recommended Volunteer workflow
RECOMMENDED_VOLUNTEER_WORKFLOW = WorkflowDefinition(
    workflow_id='recommended_volunteer',
    display_name='Recommended Volunteer',
    description='Handles volunteers who arrive via recommendation/referral',
    initial_stage='verifying_identity',
    terminal_stages=['not_registered', 'human_review'],
    stages={
        'verifying_identity': WorkflowStageDefinition(
            stage_id='verifying_identity',
            display_name='Verifying Identity',
            responsible_agent='engagement',
            valid_next_stages=['gathering_preferences', 'not_registered', 'human_review', 'paused'],
            required_fields=[],
            can_pause=True,
        ),
        'gathering_preferences': WorkflowStageDefinition(
            stage_id='gathering_preferences',
            display_name='Capturing Preferences',
            responsible_agent='engagement',
            valid_next_stages=['active', 'paused', 'human_review'],
            required_fields=[],
            can_pause=True,
        ),
        'active': WorkflowStageDefinition(
            stage_id='active',
            display_name='Matching In Progress',
            responsible_agent='fulfillment',
            valid_next_stages=['complete', 'human_review', 'paused'],
            required_fields=[],
            can_pause=True,
        ),
        'complete': WorkflowStageDefinition(
            stage_id='complete',
            display_name='Matched',
            responsible_agent='fulfillment',
            valid_next_stages=[],
            required_fields=[],
            can_pause=False,
        ),
        'not_registered': WorkflowStageDefinition(
            stage_id='not_registered',
            display_name='Not Registered',
            responsible_agent='engagement',
            valid_next_stages=[],
            required_fields=[],
            can_pause=False,
        ),
        'human_review': WorkflowStageDefinition(
            stage_id='human_review',
            display_name='Needs Human Follow-up',
            responsible_agent='engagement',
            valid_next_stages=[],
            required_fields=[],
            can_pause=False,
        ),
        'paused': WorkflowStageDefinition(
            stage_id='paused',
            display_name='Paused',
            responsible_agent='engagement',
            valid_next_stages=['verifying_identity', 'gathering_preferences'],
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
    'recommended_volunteer': RECOMMENDED_VOLUNTEER_WORKFLOW,
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
                'welcome', 'orientation_video', 'eligibility_screening',
                'contact_capture', 'registration_review', 'onboarding_complete',
                'selection_conversation', 'gathering_preferences', 'active', 'complete'
            ],
            'need_coordination': [
                'initiated', 'capturing_phone', 'resolving_coordinator', 'confirming_identity',
                'resolving_school', 'drafting_need', 'pending_approval', 'submitted', 'approved',
                'fulfillment_handoff_ready'
            ],
            'returning_volunteer': [
                're_engaging', 'profile_refresh', 'matching_ready', 'active', 'complete'
            ],
            'recommended_volunteer': [
                'verifying_identity', 'gathering_preferences', 'active', 'complete'
            ],
        }
        
        stage_order = stage_orders.get(workflow_id, [])
        
        if current_stage not in stage_order:
            if workflow.is_terminal(current_stage):
                return 100
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
