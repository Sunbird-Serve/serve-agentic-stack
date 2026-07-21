"""
SERVE Orchestrator — Gap Analyzer

Pure function: given a volunteer's facts and their desired action,
determine which ONE agent should handle the next turn.

Priority order:
  1. Identity & registration
  2. Platform eligibility
  3. Intent unclear → engagement
  4. Credential missing for desired category → selection
  5. Preferences missing → engagement
  6. Ready to match → fulfillment
  7. Fallback → engagement
"""
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class GapResult(BaseModel):
    """Output of gap analysis — which agent to invoke and why."""
    next_agent: str
    reason: str
    missing: List[str] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)


# Maps desired_action to credential category
ACTION_TO_CATEGORY = {
    "teach_english": "english_teaching",
    "teach_hindi": "hindi_teaching",
    "teach_mathematics": "mathematics_teaching",
    "teach_science": "science_teaching",
    "mentoring": "mentoring",
}


def analyze_gap(facts: Dict[str, Any], desired_action: str) -> GapResult:
    """
    Given volunteer facts and what they want to do, determine the next agent.

    Args:
        facts: The volunteer's persistent fact-set (from volunteers.facts JSONB)
        desired_action: What the volunteer wants (teach_english, find_opportunity, unknown, etc.)

    Returns:
        GapResult with next_agent, reason, missing fields, and optional params
    """

    # ── Priority 1: Identity not verified ──────────────────────────────────
    if not facts.get("identity_verified"):
        return GapResult(
            next_agent="onboarding",
            reason="Volunteer identity not yet verified",
            missing=["identity_verified"],
        )

    # ── Priority 2: Not registered ─────────────────────────────────────────
    if not facts.get("registered"):
        return GapResult(
            next_agent="onboarding",
            reason="Volunteer not yet registered in Serve Registry",
            missing=["registered"],
        )

    # ── Priority 3: Platform eligibility incomplete ────────────────────────
    eligibility_fields = ["adult_eligibility", "internet_device", "unpaid_consent"]
    missing_eligibility = [f for f in eligibility_fields if not facts.get(f)]
    if missing_eligibility:
        return GapResult(
            next_agent="onboarding",
            reason="Platform eligibility not fully confirmed",
            missing=missing_eligibility,
        )

    # ── Priority 4: Intent unclear ─────────────────────────────────────────
    if desired_action == "unknown":
        return GapResult(
            next_agent="engagement",
            reason="Volunteer intent not clear — engagement will clarify",
            missing=["intent"],
        )

    # ── Priority 5: Credential needed for desired category ─────────────────
    category = ACTION_TO_CATEGORY.get(desired_action)
    if category:
        credentials = facts.get("credentials") or {}
        credential = credentials.get(category)

        if not credential or credential.get("status") not in ("recommended", "engagement_later"):
            return GapResult(
                next_agent="selection",
                reason=f"No valid credential for {category}",
                missing=[f"credentials.{category}"],
                params={"category": category},
            )

    # ── Priority 6: Preferences missing or stale ──────────────────────────
    preferences = facts.get("preferences") or {}
    if not preferences.get("willing_to_act") or not preferences.get("subjects"):
        return GapResult(
            next_agent="engagement",
            reason="Preferences not captured or incomplete",
            missing=["preferences.subjects", "preferences.willing_to_act"],
        )

    # ── Priority 7: Ready for matching ─────────────────────────────────────
    if preferences.get("willing_to_act") == "ready_now":
        return GapResult(
            next_agent="fulfillment",
            reason="All prerequisites met — ready to match",
            missing=[],
        )

    # ── Priority 8: Has credentials but not ready ──────────────────────────
    return GapResult(
        next_agent="engagement",
        reason="Volunteer has credentials but isn't ready_now — re-engage",
        missing=["preferences.willing_to_act"],
    )
