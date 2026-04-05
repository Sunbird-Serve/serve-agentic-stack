"""
SERVE Fulfillment Agent - Match Finder

Pure Python service that finds the best open teaching need for a volunteer.
No LLM involved — deterministic search based on handoff payload.

Priority:
  1. preferred_need_id → confirm still open
  2. preferred_school_id → fetch needs, filter by time preference
  3. All schools fallback → find time-matching need across all entities
"""
import logging
import re
from typing import Any, Dict, List, Optional

from app.clients.domain_client import domain_client

logger = logging.getLogger(__name__)

# Statuses that mean a need is already taken
_BLOCKED_STATUSES = {"Assigned", "Closed", "Completed", "Cancelled"}
# Only show needs that have been approved for volunteer matching
_ALLOWED_STATUSES = {"Approved"}


class MatchResult:
    def __init__(
        self,
        status: str,                          # "found" | "multiple" | "not_found"
        candidates: Optional[List[Dict]] = None,
        reason: Optional[str] = None,
    ):
        self.status = status
        self.candidates = candidates or []
        self.reason = reason


class MatchFinder:
    """
    Finds open teaching needs for a volunteer based on their handoff payload.
    Returns up to 3 ranked candidates.
    """

    async def find(self, handoff: Dict[str, Any]) -> MatchResult:
        preferred_need_id   = handoff.get("preferred_need_id")
        preferred_school_id = handoff.get("preferred_school_id")
        preference_notes    = handoff.get("preference_notes") or ""
        continuity          = handoff.get("continuity", "same")

        preferred_time = self._extract_time_preference(preference_notes)
        logger.info(
            f"MatchFinder: continuity={continuity}, school={preferred_school_id}, "
            f"need={preferred_need_id}, time_pref={preferred_time}"
        )

        # ── 1. Try preferred need directly ───────────────────────────────────
        if preferred_need_id:
            need = await self._fetch_and_validate_need(preferred_need_id)
            if need:
                return MatchResult(status="found", candidates=[need])

        # ── 2. Try preferred school ───────────────────────────────────────────
        if preferred_school_id:
            candidates = await self._needs_for_entity(preferred_school_id, preferred_time)
            if candidates:
                return self._wrap(candidates)

        # ── 3. Fallback: search all schools ──────────────────────────────────
        logger.info("MatchFinder: no match at preferred school — searching all entities")
        all_entities_result = await domain_client.get_all_entities()
        # Unwrap MCP envelope: {"status": "success", "entities": [...]}
        entities = all_entities_result.get("entities", []) if isinstance(all_entities_result, dict) else []

        # Skip the preferred school (already checked)
        other_entities = [
            e for e in entities
            if e.get("entity_id") != preferred_school_id and e.get("id") != preferred_school_id
        ]

        for entity in other_entities[:10]:  # cap at 10 schools
            entity_id = entity.get("entity_id") or entity.get("id")
            if not entity_id:
                continue
            candidates = await self._needs_for_entity(entity_id, preferred_time)
            if candidates:
                # Tag with school name for LLM context
                for c in candidates:
                    if not c.get("school_name"):
                        c["school_name"] = entity.get("name", "")
                return self._wrap(candidates)

        return MatchResult(status="not_found", reason="no_open_needs_matching_preference")

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _needs_for_entity(
        self, entity_id: str, preferred_time: Optional[str]
    ) -> List[Dict]:
        """Fetch needs for an entity, validate each, filter by time if given."""
        result = await domain_client.get_needs_for_entity(entity_id)
        # Unwrap MCP envelope: {"status": "success", "needs": [...]}
        raw_needs = result.get("needs", []) if isinstance(result, dict) else []
        if not raw_needs:
            return []

        validated = []
        for need in raw_needs[:20]:  # cap per school
            need_id = need.get("id")
            if not need_id:
                continue
            # Skip obviously blocked statuses without fetching details
            if need.get("status") in _BLOCKED_STATUSES:
                continue
            # Only consider needs that are approved/open for matching
            if need.get("status") not in _ALLOWED_STATUSES:
                continue
            enriched = await self._fetch_and_validate_need(need_id)
            if enriched:
                validated.append(enriched)

        if not validated:
            return []

        # Filter by time preference if we have one
        if preferred_time:
            time_matches = [n for n in validated if self._time_matches(n, preferred_time)]
            if time_matches:
                return time_matches[:3]

        return validated[:3]

    async def _fetch_and_validate_need(self, need_id: str) -> Optional[Dict]:
        """Fetch need details and check it's open and not already nominated."""
        result = await domain_client.get_need_details(need_id)
        # Unwrap MCP envelope: {"status": "success", "need_details": {...}}
        details = result.get("need_details") if isinstance(result, dict) else None
        if not details:
            return None
        if details.get("status") in _BLOCKED_STATUSES:
            return None
        if details.get("status") not in _ALLOWED_STATUSES:
            return None

        return details

    def _time_matches(self, need: Dict, preferred_time: str) -> bool:
        """Check if any time slot in the need overlaps with the preferred time."""
        slots = need.get("time_slots", [])
        if not slots:
            return False
        pref_hour = self._parse_hour(preferred_time)
        if pref_hour is None:
            return False
        for slot in slots:
            start = self._parse_hour(slot.get("startTime", ""))
            end   = self._parse_hour(slot.get("endTime", ""))
            if start is not None and end is not None:
                if start <= pref_hour < end:
                    return True
            elif start is not None and abs(start - pref_hour) <= 1:
                return True
        return False

    def _extract_time_preference(self, notes: str) -> Optional[str]:
        """Extract a time hint from preference notes, e.g. '10 to 11 AM' → '10:00'."""
        if not notes:
            return None
        # Match patterns like "10 to 11 AM", "10-11am", "10:00", "10 AM"
        m = re.search(
            r"(\d{1,2})(?::(\d{2}))?\s*(?:to|-)\s*\d{1,2}|(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
            notes, re.IGNORECASE
        )
        if m:
            hour_str = m.group(1) or m.group(3)
            minute_str = m.group(2) or m.group(4) or "00"
            ampm = (m.group(5) or "").lower()
            if hour_str:
                hour = int(hour_str)
                if ampm == "pm" and hour < 12:
                    hour += 12
                return f"{hour:02d}:{minute_str}"
        return None

    def _parse_hour(self, time_str: str) -> Optional[int]:
        """Parse hour from time strings like '10:00', '2026-04-01T10:00:00Z'."""
        if not time_str:
            return None
        # ISO datetime
        m = re.search(r"T(\d{2}):(\d{2})", time_str)
        if m:
            return int(m.group(1))
        # HH:MM
        m = re.search(r"^(\d{1,2}):(\d{2})$", time_str.strip())
        if m:
            return int(m.group(1))
        return None

    def _wrap(self, candidates: List[Dict]) -> MatchResult:
        if len(candidates) == 1:
            return MatchResult(status="found", candidates=candidates)
        return MatchResult(status="multiple", candidates=candidates[:3])


# Singleton
match_finder = MatchFinder()
