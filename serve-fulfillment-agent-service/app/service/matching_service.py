"""
SERVE Fulfillment Agent - Match Finder (v2 — bulk search)

Pure Python service that finds the best open teaching need for a volunteer.
No LLM involved — deterministic search based on handoff payload.

v2 uses a single bulk MCP call (search_approved_needs) to fetch all approved
needs across all schools, then filters/ranks in Python. This replaces the
per-entity loop which was slow at scale and missed needs.

Priority:
  1. preferred_need_id → exact match
  2. preferred_school_id → needs at that school
  3. Time preference match → across all schools
  4. Any approved need → fallback
"""
import logging
import re
from typing import Any, Dict, List, Optional

from app.clients.domain_client import domain_client

logger = logging.getLogger(__name__)


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
        preferred_days = self._extract_day_preference(preference_notes)
        logger.info(
            f"MatchFinder: continuity={continuity}, school={preferred_school_id}, "
            f"need={preferred_need_id}, time_pref={preferred_time}, day_pref={preferred_days}"
        )

        # ── Bulk fetch all approved needs (single MCP call) ──────────────────
        bulk_result = await domain_client.search_approved_needs()
        all_needs = bulk_result.get("needs", []) if isinstance(bulk_result, dict) else []
        logger.info(f"MatchFinder: bulk search returned {len(all_needs)} approved needs")

        if not all_needs:
            return MatchResult(status="not_found", reason="no_approved_needs_in_system")

        # ── 1. Try preferred need directly ───────────────────────────────────
        if preferred_need_id:
            exact = [n for n in all_needs if n.get("id") == preferred_need_id]
            if exact:
                return MatchResult(status="found", candidates=exact[:1])

        # ── 2. Try preferred school ───────────────────────────────────────────
        if preferred_school_id:
            school_needs = [n for n in all_needs if n.get("entity_id") == preferred_school_id]
            if school_needs:
                ranked = self._rank(school_needs, preferred_time, preferred_days)
                return self._wrap(ranked[:3])

        # ── 3. Day + time preference match across all schools ────────────────
        if preferred_days:
            day_matches = [n for n in all_needs if self._day_matches(n, preferred_days)]
            if day_matches:
                # Further filter by time if available
                if preferred_time:
                    day_time_matches = [n for n in day_matches if self._time_matches(n, preferred_time)]
                    if day_time_matches:
                        return self._wrap(day_time_matches[:3])
                return self._wrap(day_matches[:3])

        if preferred_time:
            time_matches = [n for n in all_needs if self._time_matches(n, preferred_time)]
            if time_matches:
                return self._wrap(time_matches[:3])

        # ── 4. Fallback: return top 3 from any school ────────────────────────
        return self._wrap(all_needs[:3])

    # ── Ranking ───────────────────────────────────────────────────────────────

    def _rank(self, needs: List[Dict], preferred_time: Optional[str], preferred_days: Optional[List[str]] = None) -> List[Dict]:
        """Rank needs: day+time matching first, then day-only, then time-only, then the rest."""
        if not preferred_time and not preferred_days:
            return needs
        day_and_time = []
        day_only = []
        time_only = []
        others = []
        for n in needs:
            d_match = self._day_matches(n, preferred_days) if preferred_days else False
            t_match = self._time_matches(n, preferred_time) if preferred_time else False
            if d_match and t_match:
                day_and_time.append(n)
            elif d_match:
                day_only.append(n)
            elif t_match:
                time_only.append(n)
            else:
                others.append(n)
        return day_and_time + day_only + time_only + others

    # ── Time matching ─────────────────────────────────────────────────────────

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
        """Extract a time hint from preference notes."""
        if not notes:
            return None
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
        # Also handle "morning" / "afternoon" keywords
        lower = notes.lower()
        if "morning" in lower or "subah" in lower:
            return "09:00"
        if "afternoon" in lower or "dopahar" in lower:
            return "13:00"
        return None

    # ── Day matching ──────────────────────────────────────────────────────────

    _DAY_NAMES = {
        "monday": "monday", "mon": "monday",
        "tuesday": "tuesday", "tue": "tuesday", "tues": "tuesday",
        "wednesday": "wednesday", "wed": "wednesday",
        "thursday": "thursday", "thu": "thursday", "thurs": "thursday",
        "friday": "friday", "fri": "friday",
        "saturday": "saturday", "sat": "saturday",
        "sunday": "sunday", "sun": "sunday",
    }

    def _extract_day_preference(self, notes: str) -> Optional[List[str]]:
        """Extract preferred day names from preference notes."""
        if not notes:
            return None
        lower = notes.lower()
        found = set()
        for keyword, canonical in self._DAY_NAMES.items():
            if re.search(r"\b" + keyword + r"\b", lower):
                found.add(canonical)
        return sorted(found) if found else None

    def _day_matches(self, need: Dict, preferred_days: Optional[List[str]]) -> bool:
        """Check if a need's scheduled days overlap with preferred days."""
        if not preferred_days:
            return False
        need_days_raw = need.get("days", "")
        if not need_days_raw:
            return False
        need_days_lower = need_days_raw.lower()
        for day in preferred_days:
            # Check full name or common abbreviation
            if day in need_days_lower or day[:3] in need_days_lower:
                return True
        return False

    def _parse_hour(self, time_str: str) -> Optional[int]:
        """Parse hour from time strings like '10:00', '2026-04-01T10:00:00Z'."""
        if not time_str:
            return None
        m = re.search(r"T(\d{2}):(\d{2})", time_str)
        if m:
            return int(m.group(1))
        m = re.search(r"^(\d{1,2}):(\d{2})$", time_str.strip())
        if m:
            return int(m.group(1))
        return None

    def _wrap(self, candidates: List[Dict]) -> MatchResult:
        if not candidates:
            return MatchResult(status="not_found", reason="no_matching_needs")
        if len(candidates) == 1:
            return MatchResult(status="found", candidates=candidates)
        return MatchResult(status="multiple", candidates=candidates[:3])


# Singleton
match_finder = MatchFinder()
