"""
SERVE Selection Agent Service - Core Evaluation Logic

Silent agent — no volunteer-facing conversation.
Called after onboarding completes. Evaluates the volunteer profile
and returns: recommend | not_recommend | hold.

TODO (contributor): Implement actual evaluation criteria.
  - Profile completeness checks
  - Skill/availability validation
  - LLM-based motivation assessment (optional, via llm_adapter)
  - Flag generation for ops review
"""
import logging
from typing import Any, Dict, List

from app.schemas.selection_schemas import (
    SelectionEvaluateRequest,
    SelectionEvaluateResponse,
    SelectionOutcome,
)

logger = logging.getLogger(__name__)


class SelectionAgentService:
    """
    Stateless evaluation service.
    Receives a profile, returns a recommendation. No conversation state.
    """

    async def evaluate(self, request: SelectionEvaluateRequest) -> SelectionEvaluateResponse:
        """
        Evaluate a volunteer after onboarding.

        TODO (contributor): Replace stub with real evaluation logic.
        """
        session_id = str(request.session_id)
        logger.info(f"Selection evaluation for session {session_id}")

        # ── Stub: always recommend ────────────────────────────────────────────
        # Replace this with actual evaluation criteria.
        outcome = SelectionOutcome.RECOMMEND
        confidence = 0.5
        reason = "Stub evaluation — no criteria applied yet"
        flags: List[str] = []
        recommended_actions: List[str] = []

        # Example skeleton for contributor:
        # ──────────────────────────────────────────────────────────────────────
        # profile = request.profile
        #
        # # Check completeness
        # if not profile.skills:
        #     flags.append("no_skills_listed")
        # if not profile.availability:
        #     flags.append("no_availability")
        #
        # # Rule-based scoring
        # score = self._compute_score(profile)
        #
        # # Optional: LLM evaluation
        # from app.service.llm_adapter import llm_adapter
        # llm_result = await llm_adapter.evaluate_profile(profile.model_dump())
        #
        # # Decision
        # if score >= 0.7:
        #     outcome = SelectionOutcome.RECOMMEND
        # elif score >= 0.4:
        #     outcome = SelectionOutcome.HOLD
        # else:
        #     outcome = SelectionOutcome.NOT_RECOMMEND
        # ──────────────────────────────────────────────────────────────────────

        return SelectionEvaluateResponse(
            session_id=request.session_id,
            volunteer_id=request.volunteer_id,
            outcome=outcome,
            confidence=confidence,
            reason=reason,
            flags=flags,
            recommended_actions=recommended_actions,
        )


# Singleton
selection_agent_service = SelectionAgentService()
