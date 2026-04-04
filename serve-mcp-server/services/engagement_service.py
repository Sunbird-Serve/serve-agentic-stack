"""
SERVE MCP Server - Engagement Service
Hybrid engagement helpers used by the Engagement Agent.

The agent still interprets free-form volunteer replies locally.
This service owns stable persistence, context assembly,
and handoff payload preparation.
"""
import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

from services.session_service import SessionService
from services.serve_registry_client import (
    fulfillment_client,
    need_service_client,
    nomination_client,
    volunteering_client,
)

logger = logging.getLogger(__name__)

_DEFAULT_ENGAGEMENT_SUB_STATE = {
    "engagement_context": {},
    "continue_decision": None,
    "same_school": None,
    "same_slot": None,
    "open_to_alternatives": None,
    "continuity": None,
    "preference_notes": None,
    "handoff": {},
    "human_review_reason": None,
    "volunteer_status": None,
    "status_reason": None,
}


class EngagementService:
    def __init__(self) -> None:
        self._session_service = SessionService()

    async def get_engagement_context(self, phone: Optional[str]) -> Dict[str, Any]:
        """Fetch fulfillment history and volunteer profile by phone number."""
        if not phone:
            return {"status": "error", "error": "phone is required"}

        # Step 1: resolve volunteer by phone
        user = await volunteering_client.lookup_by_mobile(phone)
        if not user:
            return {"status": "not_found", "error": f"No volunteer found for phone {phone}"}

        volunteer_id = user.get("osid")
        if not volunteer_id:
            return {"status": "error", "error": "Volunteer record has no osid"}

        # Strip the "1-" prefix for fulfillment API calls if present
        bare_id = volunteer_id.lstrip("1-") if volunteer_id.startswith("1-") else volunteer_id

        # Step 2: fetch fulfillment history + profile in parallel
        raw_fulfillments, profile = await asyncio.gather(
            fulfillment_client.get_fulfillments_for_volunteer(bare_id),
            volunteering_client.get_user_profile(bare_id),
            return_exceptions=True,
        )

        # Step 3: enrich each fulfillment with need details
        enriched: List[Dict[str, Any]] = []
        if isinstance(raw_fulfillments, list):
            for f in raw_fulfillments:
                need_id = f.get("needId", "")
                need_detail = {}
                if need_id:
                    try:
                        need_detail = await need_service_client.get_need_details(need_id) or {}
                    except Exception:
                        pass

                # Extract school name from needPurpose/description (most reliable field)
                school_name = self._extract_school_name(
                    need_detail.get("needPurpose", "") or need_detail.get("name", "")
                )

                enriched.append({
                    "fulfillment_id":     f.get("id"),
                    "need_id":            need_id,
                    "entity_id":          need_detail.get("entity_id", ""),
                    "school_name":        school_name,
                    "need_name":          need_detail.get("name", ""),
                    "need_purpose":       need_detail.get("needPurpose", ""),
                    "subjects":           need_detail.get("subjects", []),
                    "grade_levels":       need_detail.get("grade_levels", []),
                    "days":               need_detail.get("days", ""),
                    "time_slots":         need_detail.get("time_slots", []),
                    "start_date":         need_detail.get("start_date", ""),
                    "end_date":           need_detail.get("end_date", ""),
                    "fulfillment_status": f.get("fulfillmentStatus"),
                })

        volunteer_name = user.get("full_name") or user.get("first_name") or "Volunteer"

        return {
            "status":             "success",
            "volunteer_id":       volunteer_id,
            "volunteer_name":     volunteer_name,
            "fulfillment_history": enriched,
            "volunteer_profile":  profile if isinstance(profile, dict) else None,
        }

    def _extract_school_name(self, text: str) -> str:
        """
        Extract school/college name from a need purpose string.
        e.g. "technology foundation - Grade 11(CS) Government Vocational Junior College Nampally"
             → "Government Vocational Junior College Nampally"
        """
        if not text:
            return ""
        pattern = r"((?:Government|Govt|Municipal|Private|Public|Kendriya|Navodaya|Zilla|District|State|Central|National|International|Primary|Secondary|Senior|Junior|Higher|High|Middle|Elementary|Model|Convent|Mission|DAV|DPS|KV|JNV|CBSE|ICSE|SSC|HSC|Vidyalaya|Vidyapeeth|Mandir|Niketan|Ashram|Mahavidyalaya|College|School|Academy|Institute|Parishad|Patasala|Gurukul)\b.*)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""

    async def save_confirmed_signals(
        self,
        session_id: str,
        signals: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Merge confirmed engagement signals into session sub_state and persist them."""
        session_result = await self._session_service.get_session(session_id)
        if session_result.get("status") != "success":
            return session_result

        session = session_result.get("session", {})
        sub_state = self._load_sub_state(session.get("sub_state"))
        for key, value in signals.items():
            if value is not None:
                sub_state[key] = value

        await self._session_service.update_session_context(
            session_id,
            sub_state=json.dumps(sub_state),
        )
        return {
            "status": "success",
            "saved_signals": list(signals.keys()),
            "sub_state": sub_state,
        }

    async def update_volunteer_status(
        self,
        session_id: str,
        volunteer_status: str,
        reason: Optional[str] = None,
        signals: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist the current engagement status into session sub_state and telemetry."""
        session_result = await self._session_service.get_session(session_id)
        if session_result.get("status") != "success":
            return session_result

        session = session_result.get("session", {})
        sub_state = self._load_sub_state(session.get("sub_state"))
        sub_state["volunteer_status"] = volunteer_status
        if reason:
            sub_state["status_reason"] = reason
        if signals:
            for key, value in signals.items():
                if value is not None:
                    sub_state[key] = value

        await self._session_service.update_session_context(
            session_id,
            sub_state=json.dumps(sub_state),
        )
        await self._session_service.log_event(
            session_id=session_id,
            event_type="engagement_status_updated",
            agent="engagement",
            domain="volunteer",
            source_service="engagement_agent",
            data={
                "volunteer_status": volunteer_status,
                "reason": reason,
            },
        )
        return {
            "status": "success",
            "volunteer_status": volunteer_status,
            "sub_state": sub_state,
        }

    async def prepare_fulfillment_handoff(
        self,
        session_id: str,
        signals: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build the fulfillment handoff payload from session state + engagement context."""
        session_result = await self._session_service.get_session(session_id)
        if session_result.get("status") != "success":
            return session_result

        session = session_result.get("session", {})
        sub_state = self._load_sub_state(session.get("sub_state"))
        if signals:
            for key, value in signals.items():
                if value is not None:
                    sub_state[key] = value

        volunteer_id = session.get("volunteer_id")
        if not volunteer_id:
            return {"status": "error", "error": "Session has no volunteer_id"}

        engagement_context = sub_state.get("engagement_context") or {}
        # Note: if context is missing here, we cannot re-fetch (no phone available in this path).
        # The engagement agent pre-loads and caches context in sub_state, so this should be populated.

        history = engagement_context.get("fulfillment_history") or []
        latest = history[0] if history else {}

        continuity = sub_state.get("continuity") or "different"
        volunteer_profile = engagement_context.get("volunteer_profile") or {}
        volunteer_name = (
            volunteer_profile.get("full_name")
            or volunteer_profile.get("first_name")
            or "Volunteer"
        )

        payload = {
            "volunteer_id": str(volunteer_id),
            "volunteer_name": volunteer_name,
            "continuity": continuity,
            "preferred_need_id": latest.get("need_id") if continuity == "same" else None,
            "preferred_school_id": latest.get("entity_id") if continuity == "same" else None,
            "preference_notes": sub_state.get("preference_notes"),
            "fulfillment_history": history,
        }

        sub_state["handoff"] = payload
        await self._session_service.update_session_context(
            session_id,
            sub_state=json.dumps(sub_state),
        )
        return {
            "status": "success",
            "handoff_payload": payload,
            "sub_state": sub_state,
        }

    def _load_sub_state(self, raw: Optional[str]) -> Dict[str, Any]:
        if not raw:
            return dict(_DEFAULT_ENGAGEMENT_SUB_STATE)
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return dict(_DEFAULT_ENGAGEMENT_SUB_STATE)
            state = dict(_DEFAULT_ENGAGEMENT_SUB_STATE)
            state.update(data)
            return state
        except (json.JSONDecodeError, ValueError):
            logger.warning("Malformed engagement sub_state JSON in MCP session store")
            return dict(_DEFAULT_ENGAGEMENT_SUB_STATE)


engagement_service = EngagementService()
