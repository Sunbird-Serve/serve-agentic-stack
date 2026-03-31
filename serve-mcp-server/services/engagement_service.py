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

    async def get_engagement_context(self, volunteer_id: Optional[str]) -> Dict[str, Any]:
        """Fetch fulfillment history, active nominations, and volunteer profile."""
        if not volunteer_id:
            return {
                "status": "error",
                "error": "volunteer_id is required",
            }

        completed_statuses = {"Completed", "Closed"}
        active_nom_statuses = {"Nominated", "Approved", "Proposed"}

        raw_fulfillments, all_nominations, profile = await asyncio.gather(
            fulfillment_client.get_fulfillments_for_volunteer(volunteer_id),
            nomination_client.get_nominations_for_volunteer(volunteer_id),
            volunteering_client.get_user_profile(volunteer_id),
            return_exceptions=True,
        )

        enriched: List[Dict[str, Any]] = []
        if isinstance(raw_fulfillments, list):
            for f in raw_fulfillments:
                if f.get("fulfillmentStatus") not in completed_statuses:
                    continue
                need_id = f.get("needId", "")
                need_detail = {}
                if need_id:
                    try:
                        need_detail = await need_service_client.get_need_details(need_id) or {}
                    except Exception:
                        pass
                enriched.append({
                    "fulfillment_id": f.get("id"),
                    "need_id": need_id,
                    "school_name": need_detail.get("name", ""),
                    "subjects": need_detail.get("subjects", []),
                    "grade_levels": need_detail.get("grade_levels", []),
                    "schedule": need_detail.get("days", ""),
                    "start_date": need_detail.get("start_date", ""),
                    "end_date": need_detail.get("end_date", ""),
                    "fulfillment_status": f.get("fulfillmentStatus"),
                })

        active_noms: List[Dict[str, Any]] = []
        if isinstance(all_nominations, list):
            active_noms = [n for n in all_nominations if n.get("nominationStatus") in active_nom_statuses]

        return {
            "status": "success",
            "fulfillment_history": enriched,
            "has_active_nomination": len(active_noms) > 0,
            "active_nominations": active_noms,
            "volunteer_profile": profile if isinstance(profile, dict) else None,
        }

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
        if not engagement_context:
            engagement_context = await self.get_engagement_context(volunteer_id)
            if engagement_context.get("status") == "success":
                sub_state["engagement_context"] = engagement_context

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
            "preferred_school_id": None,
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
