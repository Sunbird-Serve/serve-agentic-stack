"""
SERVE Need Agent Service - Core Logic (L3.5)

Architecture:
  - High-level workflow stages are controlled by a state machine (deterministic).
  - Within RESOLVING_COORDINATOR and RESOLVING_SCHOOL, an LLM tool-calling loop
    (via llm_adapter) handles all branching logic autonomously (non-deterministic).
  - All other stages use plain LLM text generation.

Sub-state JSON schema (stored in session.sub_state between turns):
  {
    "coordinator": {
      "phone": str | null,
      "email": str | null,
      "name": str | null,
      "phone_tried": bool,
      "email_tried": bool,
      "coordinator_id": str | null,     # Serve Registry osid
      "coordinator_name": str | null,
      "is_verified": bool
    },
    "school": {
      "school_id": str | null,          # Serve Need Service entity UUID
      "school_name": str | null,
      "linked_schools_checked": bool,
      "udise_hint": str | null,
      "previous_needs": list,
      "is_new_school": bool
    }
  }
"""
import copy
import json
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.need_schemas import (
    NeedWorkflowState,
    CoordinatorResolutionStatus,
    SchoolResolutionStatus,
    NeedSessionState,
    NeedAgentTurnRequest,
    NeedAgentTurnResponse,
    NeedDraft,
    Coordinator,
    School,
    MANDATORY_NEED_FIELDS,
)
from app.clients import domain_client as _mcp_client
from app.service.llm_adapter import llm_adapter

logger = logging.getLogger(__name__)


# ── Sub-state helpers ─────────────────────────────────────────────────────────

def _load_sub_state(sub_state_str: Optional[str]) -> Dict[str, Any]:
    if not sub_state_str:
        return {"coordinator": {}, "school": {}}
    try:
        data = json.loads(sub_state_str)
        data.setdefault("coordinator", {})
        data.setdefault("school", {})
        return data
    except Exception:
        return {"coordinator": {}, "school": {}}


def _dump_sub_state(sub_state: Dict[str, Any]) -> str:
    return json.dumps(sub_state)


# ── Phone extraction ──────────────────────────────────────────────────────────

_PHONE_RE = re.compile(
    r"(?:\+?91[-.\s]?)?(?:\(?0\)?[-.\s]?)?"
    r"[6-9]\d{9}"
    r"|(?:\+\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{4}"
)


def _extract_phone(text: str) -> Optional[str]:
    match = _PHONE_RE.search(text.replace(" ", ""))
    if match:
        digits = re.sub(r"\D", "", match.group())
        if len(digits) >= 10:
            return "+" + digits if not digits.startswith("+") else digits
    return None


# ── Need field extraction (regex) ────────────────────────────────────────────

class NeedDetailExtractor:
    """Regex-based extraction of need fields from free-text coordinator messages."""

    SUBJECT_MAP = {
        "math": "mathematics", "maths": "mathematics", "mathematics": "mathematics",
        "science": "science", "physics": "science", "chemistry": "science", "biology": "science",
        "english": "english", "eng": "english",
        "hindi": "hindi",
        "social": "social_studies", "history": "social_studies", "geography": "social_studies",
        "computer": "computer_basics", "computers": "computer_basics", "ict": "computer_basics",
        "spoken english": "spoken_english",
        "art": "art", "music": "music",
    }

    GRADE_RE = re.compile(
        r"\b(?:grade|class|std|standard)s?\s*(\d{1,2})\b"
        r"|\b(\d{1,2})(?:st|nd|rd|th)?\s*(?:grade|class|std)\b"
        r"|\bgrade\s+(\d{1,2})\s*(?:to|-|through)\s*(\d{1,2})\b",
        re.IGNORECASE,
    )
    STUDENT_RE = re.compile(r"\b(\d+)\s*(?:students?|kids?|children|pupils?)\b", re.IGNORECASE)
    DURATION_RE = re.compile(r"\b(\d+)\s*(?:weeks?|months?)\b", re.IGNORECASE)
    DATE_RE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})")
    TIME_RE = re.compile(
        r"\b(\d{1,2}(?::\d{2})?(?:\s*[ap]m)?)\s*(?:to|-)\s*(\d{1,2}(?::\d{2})?(?:\s*[ap]m)?)\b"
        r"|\b(morning|afternoon|evening|weekday|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        re.IGNORECASE,
    )
    FREQ_RE = re.compile(
        r"\b(\d+)\s*(?:times?|days?)\s*(?:a|per)\s*week\b"
        r"|\b(daily|everyday|every day|weekly|twice\s+a\s+week|thrice\s+a\s+week|alternate\s+days?)\b",
        re.IGNORECASE,
    )
    DAY_RE = re.compile(
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday"
        r"|mon|tue|wed|thu|fri|sat|sun"
        r"|weekdays?|weekends?)\b",
        re.IGNORECASE,
    )
    MONTH_MAP = {
        "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
        "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6,
        "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    }
    _MONTHS_PAT = (
        "january|february|march|april|may|june|july|august|september|october|november|december"
        "|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
    )
    MONTH_DATE_RE = re.compile(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + _MONTHS_PAT + r")\b"
        r"|\b(" + _MONTHS_PAT + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b",
        re.IGNORECASE,
    )

    def extract_subjects(self, text: str) -> List[str]:
        found = set()
        lower = text.lower()
        for keyword, canonical in self.SUBJECT_MAP.items():
            if keyword in lower:
                found.add(canonical)
        return list(found)

    def extract_grades(self, text: str) -> List[str]:
        found = set()
        for match in self.GRADE_RE.finditer(text):
            groups = [g for g in match.groups() if g is not None]
            if len(groups) == 2:
                try:
                    lo, hi = int(groups[0]), int(groups[1])
                    for g in range(lo, hi + 1):
                        if 1 <= g <= 12:
                            found.add(str(g))
                except ValueError:
                    pass
            elif groups:
                g = int(groups[0])
                if 1 <= g <= 12:
                    found.add(str(g))
        return list(found)

    def extract_student_count(self, text: str) -> Optional[int]:
        # Primary: explicit mention of students/kids/children
        m = self.STUDENT_RE.search(text)
        if m:
            count = int(m.group(1))
            if 1 <= count <= 2000:
                return count
        # Fallback: short message that is just a number (coordinator answering "how many students?")
        # Only if no grade pattern is present (to avoid confusing "Grade 6" with student count)
        stripped = text.strip()
        if re.match(r'^\d+$', stripped):
            count = int(stripped)
            if 1 <= count <= 2000:
                return count
        # Also match "about 30", "around 50", "approximately 40"
        m2 = re.search(r'\b(?:about|around|approximately|roughly|~)\s*(\d+)\b', text, re.IGNORECASE)
        if m2:
            count = int(m2.group(1))
            if 1 <= count <= 2000:
                return count
        return None

    def extract_time_slots(self, text: str) -> List[str]:
        found = []
        for m in self.TIME_RE.finditer(text):
            slot = " ".join(g for g in m.groups() if g)
            if slot:
                found.append(slot.strip())
        return list(set(found))

    def extract_schedule(self, text: str) -> Optional[str]:
        # First try frequency phrases (twice a week, 3 days a week, daily, etc.)
        m = self.FREQ_RE.search(text)
        if m:
            groups = [g for g in m.groups() if g]
            if groups:
                raw = groups[0].strip().lower()
                raw = re.sub(r"times?\s+a\s+week", "days a week", raw)
                raw = re.sub(r"days?\s+a\s+week", "days a week", raw)
                return raw.title()
        # Fall back to day names — collect all mentioned days
        days = self.DAY_RE.findall(text)
        if days:
            # Deduplicate preserving order
            seen = set()
            unique = []
            for d in days:
                key = d.lower()
                if key not in seen:
                    seen.add(key)
                    unique.append(d.title())
            return ", ".join(unique)
        return None

    def extract_start_date(self, text: str) -> Optional[str]:
        today = date.today()
        lower = text.lower()
        if "next week" in lower:
            from datetime import timedelta
            delta = (7 - today.weekday()) or 7
            return (today + timedelta(days=delta)).isoformat()
        if "next month" in lower:
            m = today.month % 12 + 1
            y = today.year + (1 if today.month == 12 else 0)
            return f"{y}-{m:02d}-01"
        if any(w in lower for w in ("immediately", "asap", "as soon as possible")):
            return today.isoformat()
        # Numeric date: DD/MM/YYYY or DD-MM-YYYY
        match = self.DATE_RE.search(text)
        if match:
            d, mo, y = match.groups()
            if len(y) == 2:
                y = f"20{y}"
            try:
                return date(int(y), int(mo), int(d)).isoformat()
            except ValueError:
                pass
        # Month-name + day: "1st April", "April 1", "1 April" etc.
        m2 = self.MONTH_DATE_RE.search(lower)
        if m2:
            g = m2.groups()
            if g[0] and g[1]:
                day_str, month_str = g[0], g[1]
            elif g[2] and g[3]:
                month_str, day_str = g[2], g[3]
            else:
                return None
            month_num = self.MONTH_MAP.get(month_str.lower())
            if month_num:
                try:
                    candidate = date(2026, month_num, int(day_str))
                    return candidate.isoformat()
                except ValueError:
                    pass
        # Bare month name: "April se", "April mein", "from April", just "April"
        bare_month_re = re.compile(
            r"\b(" + "|".join(self.MONTH_MAP.keys()) + r")\b",
            re.IGNORECASE,
        )
        m3 = bare_month_re.search(lower)
        if m3:
            month_num = self.MONTH_MAP.get(m3.group(1).lower())
            if month_num:
                return f"2026-{month_num:02d}-01"
        return None

    def extract_duration(self, text: str) -> Optional[int]:
        m = self.DURATION_RE.search(text)
        if m:
            val = int(m.group(1))
            if "month" in m.group(0).lower():
                val *= 4
            if 1 <= val <= 52:
                return val
        return None

    def extract_all(self, text: str, existing: Optional[Dict] = None) -> Dict[str, Any]:
        extracted: Dict[str, Any] = {}
        existing = existing or {}

        subjects = self.extract_subjects(text)
        if subjects:
            merged = list(set(existing.get("subjects", []) + subjects))
            extracted["subjects"] = merged

        grades = self.extract_grades(text)
        if grades:
            merged = list(set(existing.get("grade_levels", []) + grades))
            extracted["grade_levels"] = sorted(merged, key=lambda x: int(x))

        # student_count: removed deterministic extraction — LLM handles this intelligently
        # when user says "grade 6 - 30, grade 7 - 40", LLM can ask clarifying questions

        slots = self.extract_time_slots(text)
        if slots and not existing.get("time_slots"):
            extracted["time_slots"] = slots

        start = self.extract_start_date(text)
        if start:
            extracted["start_date"] = start

        dur = self.extract_duration(text)
        if dur is not None:
            extracted["duration_weeks"] = dur

        schedule = self.extract_schedule(text)
        if schedule:
            extracted["schedule_preference"] = schedule

        return extracted


_extractor = NeedDetailExtractor()


# ── NeedAgentService ──────────────────────────────────────────────────────────

class NeedAgentService:
    """
    L3.5 Need Agent Service.

    The state machine controls stage transitions (deterministic).
    Within resolution stages, an LLM tool-calling loop handles ambiguity.
    """

    # ── Public entry point ────────────────────────────────────────────────────

    async def process_turn(self, request: NeedAgentTurnRequest) -> NeedAgentTurnResponse:
        stage = request.session_state.stage
        sub = _load_sub_state(request.session_state.sub_state)

        dispatch = {
            NeedWorkflowState.INITIATED.value:              self._handle_initiated,
            NeedWorkflowState.CAPTURING_PHONE.value:        self._handle_capturing_phone,
            NeedWorkflowState.RESOLVING_COORDINATOR.value:  self._handle_resolving_coordinator,
            NeedWorkflowState.CONFIRMING_IDENTITY.value:    self._handle_confirming_identity,
            NeedWorkflowState.RESOLVING_SCHOOL.value:       self._handle_resolving_school,
            NeedWorkflowState.DRAFTING_NEED.value:          self._handle_drafting_need,
            NeedWorkflowState.PENDING_APPROVAL.value:       self._handle_pending_approval,
            NeedWorkflowState.SUBMITTED.value:              self._handle_submitted,
            NeedWorkflowState.REFINEMENT_REQUIRED.value:    self._handle_refinement,
            NeedWorkflowState.PAUSED.value:                 self._handle_paused,
            NeedWorkflowState.HUMAN_REVIEW.value:           self._handle_human_review,
        }

        handler = dispatch.get(stage, self._handle_fallback)
        response = await handler(request, sub)

        # Auto-advance: if the handler returned an empty message and transitioned to a
        # new stage, immediately re-dispatch so the user gets a real response this turn.
        if not response.assistant_message and response.state != stage:
            next_stage = response.state
            next_handler = dispatch.get(next_stage)
            if next_handler:
                logger.info(f"[process_turn] auto-advancing {stage!r} → {next_stage!r}")
                # Rebuild request with updated sub_state and stage
                advanced_session = copy.copy(request.session_state)
                advanced_session.stage = next_stage
                advanced_session.sub_state = response.sub_state
                advanced_request = copy.copy(request)
                advanced_request.session_state = advanced_session
                next_sub = _load_sub_state(response.sub_state)
                response = await next_handler(advanced_request, next_sub)

        return response

    # ── Stage: INITIATED ──────────────────────────────────────────────────────

    async def _handle_initiated(
        self, request: NeedAgentTurnRequest, sub: Dict
    ) -> NeedAgentTurnResponse:
        channel = request.session_state.channel

        # Resolve phone from channel_metadata (present for WhatsApp and for Web UI
        # when the pre-screen already captured the number before the chat started).
        channel_meta = (
            request.channel_metadata
            or (request.session_state.channel_metadata if request.session_state.channel_metadata else {})
        )
        phone = (
            channel_meta.get("phone_number")
            or channel_meta.get("actor_id")
            or ""
        )

        if phone:
            # Phone already known — skip CAPTURING_PHONE and auto-advance to
            # RESOLVING_COORDINATOR so the tool loop runs immediately on the next dispatch.
            sub["coordinator"]["phone"] = phone
            return self._build_response(
                message=None,
                next_state=NeedWorkflowState.RESOLVING_COORDINATOR.value,
                sub=sub,
                session_state=request.session_state,
                auto_advance=True,
            )
        elif channel == "whatsapp":
            # WhatsApp but no phone in metadata (shouldn't normally happen)
            sub["coordinator"]["phone"] = None
            return self._build_response(
                message=None,
                next_state=NeedWorkflowState.RESOLVING_COORDINATOR.value,
                sub=sub,
                session_state=request.session_state,
                auto_advance=True,
            )
        else:
            # Web UI without pre-captured phone — ask for it in the chat
            next_state = NeedWorkflowState.CAPTURING_PHONE.value
            msg = await llm_adapter.generate_response(
                stage="initiated",
                messages=[],
                user_message=request.user_message,
            )

        return self._build_response(
            message=msg,
            next_state=next_state,
            sub=sub,
            session_state=request.session_state,
        )

    # ── Stage: CAPTURING_PHONE ────────────────────────────────────────────────

    async def _handle_capturing_phone(
        self, request: NeedAgentTurnRequest, sub: Dict
    ) -> NeedAgentTurnResponse:
        # Phone may arrive via channel_metadata (re-sent by client on every turn)
        channel_meta = (
            request.channel_metadata
            or (request.session_state.channel_metadata if request.session_state.channel_metadata else {})
        )
        phone = (
            channel_meta.get("phone_number")
            or _extract_phone(request.user_message)
        )

        if phone:
            sub["coordinator"]["phone"] = phone
            next_state = NeedWorkflowState.RESOLVING_COORDINATOR.value
            msg = await llm_adapter.generate_response(
                stage="resolving_coordinator",
                messages=request.conversation_history,
                user_message=request.user_message,
            )
        else:
            next_state = NeedWorkflowState.CAPTURING_PHONE.value
            msg = await llm_adapter.generate_response(
                stage="capturing_phone",
                messages=request.conversation_history,
                user_message=request.user_message,
            )

        return self._build_response(
            message=msg,
            next_state=next_state,
            sub=sub,
            session_state=request.session_state,
        )

    # ── Stage: RESOLVING_COORDINATOR (L3.5) ───────────────────────────────────

    async def _handle_resolving_coordinator(
        self, request: NeedAgentTurnRequest, sub: Dict
    ) -> NeedAgentTurnResponse:
        coord_ctx = sub["coordinator"]
        school_ctx = sub["school"]

        # Already fully resolved — skip straight to drafting
        if coord_ctx.get("coordinator_id") and school_ctx.get("school_id"):
            return self._build_response(
                message=None,
                next_state=NeedWorkflowState.DRAFTING_NEED.value,
                sub=sub,
                session_state=request.session_state,
                auto_advance=True,
            )

        # Coordinator resolved but school not yet — hand off to school stage
        if coord_ctx.get("coordinator_id"):
            return self._build_response(
                message=None,
                next_state=NeedWorkflowState.RESOLVING_SCHOOL.value,
                sub=sub,
                session_state=request.session_state,
                auto_advance=True,
            )

        # Absorb any info provided in this message before handing to LLM
        if "@" in request.user_message and not coord_ctx.get("email"):
            email_match = re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", request.user_message, re.I)
            if email_match:
                coord_ctx["email"] = email_match.group(0)

        if not coord_ctx.get("name"):
            name_match = re.search(
                r"(?:i['\u2019]?m|my name is|this is|call me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
                request.user_message, re.I,
            )
            if name_match:
                coord_ctx["name"] = name_match.group(1).title()

        # Build tool executor — handles both coordinator AND school tools
        async def coordinator_tool_executor(tool_name: str, tool_input: Dict) -> Dict:
            if tool_name == "lookup_coordinator_by_phone":
                coord_ctx["phone_tried"] = True
                return await domain_client.resolve_coordinator_identity(
                    whatsapp_number=tool_input.get("phone")
                )
            if tool_name == "lookup_coordinator_by_email":
                coord_ctx["email_tried"] = True
                return await domain_client.resolve_coordinator_identity(
                    email=tool_input.get("email")
                )
            if tool_name == "register_new_coordinator":
                return await domain_client.create_coordinator(
                    name=tool_input.get("name", ""),
                    whatsapp_number=tool_input.get("phone"),
                    email=tool_input.get("email"),
                )
            # School tools — available in the combined loop
            if tool_name == "get_schools_for_coordinator":
                school_ctx["linked_schools_checked"] = True
                return await domain_client.resolve_school_context(
                    coordinator_id=tool_input.get("coordinator_id")
                )
            if tool_name == "search_school":
                hint = tool_input.get("hint", "")
                school_ctx["udise_hint"] = hint
                return await domain_client.resolve_school_context(school_hint=hint)
            if tool_name == "fetch_previous_needs":
                result = await domain_client.fetch_previous_need_context(
                    school_id=tool_input.get("school_id", "")
                )
                if result.get("status") == "success":
                    school_ctx["previous_needs"] = result.get("previous_needs", [])
                    logger.info(f"[coordinator_loop] fetch_previous_needs stored: count={len(school_ctx['previous_needs'])}")
                return result
            if tool_name == "link_coordinator_to_school":
                return await domain_client.map_coordinator_to_school(
                    coordinator_id=tool_input.get("coordinator_id", ""),
                    school_id=tool_input.get("school_id", ""),
                )
            if tool_name == "create_new_school":
                school_ctx["is_new_school"] = True
                return await domain_client.create_basic_school_context(
                    name=tool_input.get("name", ""),
                    location=tool_input.get("district") or tool_input.get("state") or "",
                    contact_number=tool_input.get("contact_number") or coord_ctx.get("phone"),
                    coordinator_id=coord_ctx.get("coordinator_id"),
                )
            logger.warning(f"Unknown tool in coordinator loop: {tool_name}")
            return {"status": "error", "error": f"Unknown tool: {tool_name}"}

        # Build messages for tool loop
        initial_messages = self._build_resolution_messages(request, coord_ctx)

        system_prompt = llm_adapter.build_coordinator_system_prompt(coord_ctx, school_ctx)
        msg, tool_results = await llm_adapter.run_tool_loop(
            system_prompt=system_prompt,
            initial_messages=initial_messages,
            tools=llm_adapter.COMBINED_RESOLUTION_TOOLS,
            tool_executor=coordinator_tool_executor,
            stage="coordinator",
        )

        # If ALL tool calls failed (MCP unavailable), override Claude's response
        # to prevent hallucinated "I can see you're in our system" messages.
        all_failed = bool(tool_results) and all(
            r.get("serve_system_available") is False or r.get("status") == "error"
            for r in tool_results.values()
        )
        if all_failed:
            msg = (
                "I'm having trouble accessing our records right now. "
                "Could you share your email address so I can try another way to look you up?"
            )

        # Check resolution outcome from tool results.
        # Guard: only accept an ID that looks like a real DB record (non-trivial string).
        # This prevents a hallucinated "linked" status from leaking into sub_state.
        def _is_real_id(value: Any) -> bool:
            return bool(value and isinstance(value, str) and len(value) > 4)

        for _tool_name, result in tool_results.items():
            if result.get("serve_system_available") is False:
                # Tool failure — don't treat as resolved, let Claude ask for more info
                continue
            if result.get("status") == "linked":
                coordinator = result.get("coordinator") or {}
                real_id = coordinator.get("id") or coordinator.get("osid")
                if _is_real_id(real_id):
                    coord_ctx["coordinator_id"] = real_id
                    coord_ctx["coordinator_name"] = coordinator.get("name") or coord_ctx.get("name")
                    coord_ctx["is_verified"] = coordinator.get("is_verified", False)
                    break
            if result.get("status") in ("success", "created") and _is_real_id(result.get("id")):
                # create_coordinator result
                coord_ctx["coordinator_id"] = result.get("id")
                coord_ctx["coordinator_name"] = result.get("name") or coord_ctx.get("name")
                coord_ctx["is_verified"] = False
                break

        # Extract school resolution outcome from tool results (school tools run in same loop)
        for tool_name, result in tool_results.items():
            if result.get("serve_system_available") is False:
                continue
            if tool_name in ("get_schools_for_coordinator", "search_school"):
                if result.get("status") == "multiple":
                    # Multiple schools — Claude will ask coordinator to pick.
                    # Mark this so _handle_resolving_school doesn't reset linked_schools_checked.
                    school_ctx["multiple_schools_presented"] = True
                    break
                school = result.get("school") or {}
                real_id = school.get("id")
                if _is_real_id(real_id) and result.get("status") in ("existing", "success", "linked", "ambiguous"):
                    school_ctx["school_id"] = real_id
                    school_ctx["school_name"] = school.get("name")
                    school_ctx["multiple_schools_presented"] = False
                    break
            if tool_name == "link_coordinator_to_school":
                # Result is {"success": True, "school_id": "...", "coordinator_id": "..."}
                real_id = result.get("school_id")
                if _is_real_id(real_id) and result.get("success"):
                    school_ctx["school_id"] = real_id
                    school_ctx["multiple_schools_presented"] = False
                    break
            if tool_name == "create_new_school":
                school = result.get("school") or {}
                real_id = result.get("id") or school.get("id")
                school_name = result.get("name") or school.get("name")
                if _is_real_id(real_id):
                    school_ctx["school_id"] = real_id
                    school_ctx["school_name"] = school_name
                    school_ctx["multiple_schools_presented"] = False
                    break

        sub["coordinator"] = coord_ctx
        sub["school"] = school_ctx

        # Determine next state based on what was resolved
        coord_resolved = bool(coord_ctx.get("coordinator_id"))
        school_resolved = bool(school_ctx.get("school_id"))

        if coord_resolved and school_resolved:
            next_state = NeedWorkflowState.CONFIRMING_IDENTITY.value
            # Generate identity confirmation message — LLM presents coordinator+school
            # and asks for confirmation before moving to need capture.
            msg = await llm_adapter.generate_response(
                stage="confirming_identity",
                messages=request.conversation_history,
                user_message=request.user_message,
                coordinator_context=coord_ctx,
                school_context=school_ctx,
            )
        elif coord_resolved:
            next_state = NeedWorkflowState.RESOLVING_SCHOOL.value
        else:
            next_state = NeedWorkflowState.RESOLVING_COORDINATOR.value

        confirmed: Dict = {}
        if coord_resolved:
            confirmed["coordinator_name"] = coord_ctx.get("coordinator_name")
            confirmed["coordinator_id"] = coord_ctx.get("coordinator_id")
        if school_resolved:
            confirmed["school_name"] = school_ctx.get("school_name")
            confirmed["school_id"] = school_ctx.get("school_id")

        return self._build_response(
            message=msg,
            next_state=next_state,
            sub=sub,
            session_state=request.session_state,
            confirmed_fields=confirmed,
        )

    # ── Stage: CONFIRMING_IDENTITY ────────────────────────────────────────────

    async def _handle_confirming_identity(
        self, request: NeedAgentTurnRequest, sub: Dict
    ) -> NeedAgentTurnResponse:
        coord_ctx = sub["coordinator"]
        school_ctx = sub["school"]
        lower = request.user_message.lower()

        # Detect name correction — coordinator provides corrected name inline
        # e.g. "mera naam Rajesh hai, Rakesh nahi" / "my name is Rajesh not Rakesh" / "naam Rajesh hai"
        name_correction_patterns = [
            r"(?:mera\s+naam|my\s+name\s+is|naam\s+hai|naam\s+h)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            r"(?:not|nahi|nhi)\s+\w+[,.]?\s+(?:it['\u2019]?s|its|naam)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            r"(?:spelling\s+wrong|naam\s+galat)[^,]*[,.]?\s+(?:it['\u2019]?s|its|naam\s+hai?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        ]
        corrected_name = None
        for pattern in name_correction_patterns:
            m = re.search(pattern, request.user_message, re.IGNORECASE)
            if m:
                corrected_name = m.group(1).title()
                break
        # Fallback: message contains correction signal + a capitalized name token
        if not corrected_name:
            correction_signals_name = {"wrong", "galat", "spelling", "nahi", "not", "correct it", "change"}
            if any(s in lower for s in correction_signals_name):
                name_m = re.search(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?)\b", request.user_message)
                if name_m:
                    corrected_name = name_m.group(1).title()

        if corrected_name:
            # Update coordinator name in sub_state and proceed to drafting
            coord_ctx["coordinator_name"] = corrected_name
            sub["coordinator"] = coord_ctx
            logger.info(f"[confirming_identity] name corrected to: {corrected_name!r}")
            previous_needs = school_ctx.get("previous_needs", [])
            msg = await llm_adapter.generate_response(
                stage="drafting_need",
                messages=request.conversation_history,
                user_message=request.user_message,
                coordinator_context=coord_ctx,
                school_context=school_ctx,
                need_draft={},
                missing_fields=["subjects", "grade_levels", "student_count", "schedule_preference", "start_date"],
                previous_needs=previous_needs if previous_needs else None,
            )
            return self._build_response(
                message=msg,
                next_state=NeedWorkflowState.DRAFTING_NEED.value,
                sub=sub,
                session_state=request.session_state,
                confirmed_fields={
                    "coordinator_name": corrected_name,
                    "school_name": school_ctx.get("school_name"),
                },
            )

        # Detect generic correction — coordinator says something is wrong (no name provided)
        correction_signals = {"no", "nahi", "nope", "wrong", "galat", "change", "different", "alag"}
        if any(s in lower for s in correction_signals):
            # Send back to coordinator resolution
            msg = await llm_adapter.generate_response(
                stage="resolving_coordinator",
                messages=request.conversation_history,
                user_message=request.user_message,
                coordinator_context=coord_ctx,
                school_context=school_ctx,
            )
            return self._build_response(
                message=msg,
                next_state=NeedWorkflowState.RESOLVING_COORDINATOR.value,
                sub=sub,
                session_state=request.session_state,
            )

        # Detect confirmation — coordinator says yes/correct
        confirm_signals = {
            "yes", "haan", "ha", "han", "correct", "sahi", "theek", "bilkul",
            "ok", "okay", "right", "confirm", "sure", "aage", "proceed",
        }
        if any(s in lower for s in confirm_signals):
            previous_needs = school_ctx.get("previous_needs", [])
            msg = await llm_adapter.generate_response(
                stage="drafting_need",
                messages=request.conversation_history,
                user_message=request.user_message,
                coordinator_context=coord_ctx,
                school_context=school_ctx,
                need_draft={},
                missing_fields=["subjects", "grade_levels", "student_count", "schedule_preference", "start_date"],
                previous_needs=previous_needs if previous_needs else None,
            )
            return self._build_response(
                message=msg,
                next_state=NeedWorkflowState.DRAFTING_NEED.value,
                sub=sub,
                session_state=request.session_state,
                confirmed_fields={
                    "coordinator_name": coord_ctx.get("coordinator_name"),
                    "school_name": school_ctx.get("school_name"),
                },
            )

        # Ambiguous — re-ask for confirmation
        msg = await llm_adapter.generate_response(
            stage="confirming_identity",
            messages=request.conversation_history,
            user_message=request.user_message,
            coordinator_context=coord_ctx,
            school_context=school_ctx,
        )
        return self._build_response(
            message=msg,
            next_state=NeedWorkflowState.CONFIRMING_IDENTITY.value,
            sub=sub,
            session_state=request.session_state,
        )

    # ── Stage: RESOLVING_SCHOOL (L3.5) ────────────────────────────────────────

    async def _handle_resolving_school(
        self, request: NeedAgentTurnRequest, sub: Dict
    ) -> NeedAgentTurnResponse:
        coord_ctx = sub["coordinator"]
        school_ctx = sub["school"]

        # Already resolved — skip to drafting
        if school_ctx.get("school_id"):
            return self._build_response(
                message=None,
                next_state=NeedWorkflowState.DRAFTING_NEED.value,
                sub=sub,
                session_state=request.session_state,
                auto_advance=True,
            )

        coordinator_id = coord_ctx.get("coordinator_id")

        # Build tool executor
        async def school_tool_executor(tool_name: str, tool_input: Dict) -> Dict:
            if tool_name == "get_schools_for_coordinator":
                school_ctx["linked_schools_checked"] = True
                return await domain_client.resolve_school_context(
                    coordinator_id=tool_input.get("coordinator_id")
                )
            if tool_name == "search_school":
                hint = tool_input.get("hint", "")
                school_ctx["udise_hint"] = hint
                return await domain_client.resolve_school_context(school_hint=hint)
            if tool_name == "fetch_previous_needs":
                result = await domain_client.fetch_previous_need_context(
                    school_id=tool_input.get("school_id", "")
                )
                if result.get("status") == "success":
                    school_ctx["previous_needs"] = result.get("previous_needs", [])
                    logger.info(f"[school_loop] fetch_previous_needs stored: count={len(school_ctx['previous_needs'])}")
                return result
            if tool_name == "link_coordinator_to_school":
                return await domain_client.map_coordinator_to_school(
                    coordinator_id=tool_input.get("coordinator_id", ""),
                    school_id=tool_input.get("school_id", ""),
                )
            if tool_name == "create_new_school":
                school_ctx["is_new_school"] = True
                return await domain_client.create_basic_school_context(
                    name=tool_input.get("name", ""),
                    location=tool_input.get("district") or tool_input.get("state") or "",
                    contact_number=tool_input.get("contact_number") or coord_ctx.get("phone"),
                    coordinator_id=coordinator_id,
                )
            logger.warning(f"Unknown tool in school loop: {tool_name}")
            return {"status": "error", "error": f"Unknown tool: {tool_name}"}

        # Build initial messages
        initial_messages = self._build_resolution_messages(request, {**coord_ctx, **school_ctx})
        system_prompt = llm_adapter.build_school_system_prompt(coord_ctx, school_ctx)

        msg, tool_results = await llm_adapter.run_tool_loop(
            system_prompt=system_prompt,
            initial_messages=initial_messages,
            tools=llm_adapter.SCHOOL_TOOLS,
            tool_executor=school_tool_executor,
            stage="school",
        )

        # If ALL tool calls failed (MCP unavailable), override Claude's response
        # to prevent hallucinated school resolution.
        all_failed = bool(tool_results) and all(
            r.get("serve_system_available") is False or r.get("status") == "error"
            for r in tool_results.values()
        )
        if all_failed:
            msg = (
                "I'm having trouble accessing our school records right now. "
                "Could you share your school's UDISE code or name? I'll try again."
            )

        # Extract resolution outcome from tool results.
        # Guard: only accept a school ID that is a real DB record.
        # This prevents hallucinated school names from leaking into sub_state.
        def _is_real_id(value: Any) -> bool:  # noqa: F811 (shadows outer, intentional)
            return bool(value and isinstance(value, str) and len(value) > 4)

        for tool_name, result in tool_results.items():
            if result.get("serve_system_available") is False:
                continue
            if tool_name in ("get_schools_for_coordinator", "search_school"):
                if result.get("status") == "multiple":
                    # Multiple schools — Claude will present options. Mark this so we
                    # don't reset linked_schools_checked on the next turn.
                    school_ctx["multiple_schools_presented"] = True
                    break
                school = result.get("school") or {}
                real_id = school.get("id")
                if _is_real_id(real_id) and result.get("status") in ("existing", "success", "linked", "ambiguous"):
                    school_ctx["school_id"] = real_id
                    school_ctx["school_name"] = school.get("name")
                    school_ctx["multiple_schools_presented"] = False
                    break
            if tool_name == "link_coordinator_to_school":
                # Result is {"success": True, "school_id": "...", "coordinator_id": "..."}
                real_id = result.get("school_id")
                if _is_real_id(real_id) and result.get("success"):
                    school_ctx["school_id"] = real_id
                    school_ctx["multiple_schools_presented"] = False
                    break
            if tool_name == "create_new_school":
                school = result.get("school") or {}
                real_id = result.get("id") or school.get("id")
                school_name = result.get("name") or school.get("name")
                if _is_real_id(real_id):
                    school_ctx["school_id"] = real_id
                    school_ctx["school_name"] = school_name
                    school_ctx["multiple_schools_presented"] = False
                    break

        sub["school"] = school_ctx
        resolved = bool(school_ctx.get("school_id"))
        next_state = (
            NeedWorkflowState.DRAFTING_NEED.value
            if resolved
            else NeedWorkflowState.RESOLVING_SCHOOL.value
        )

        confirmed = {}
        if resolved:
            confirmed = {
                "school_name": school_ctx.get("school_name"),
                "school_id": school_ctx.get("school_id"),
            }

        return self._build_response(
            message=msg,
            next_state=next_state,
            sub=sub,
            session_state=request.session_state,
            confirmed_fields=confirmed,
        )

    # ── Stage: DRAFTING_NEED ──────────────────────────────────────────────────

    async def _handle_drafting_need(
        self, request: NeedAgentTurnRequest, sub: Dict
    ) -> NeedAgentTurnResponse:
        session_id = str(request.session_id)
        coord_ctx = sub["coordinator"]
        school_ctx = sub["school"]

        # Fetch existing draft from MCP
        ctx_result = await domain_client.resume_need_context(session_id)
        existing_draft: Dict = {}
        if ctx_result.get("status") == "success":
            existing_draft = ctx_result.get("need_draft") or ctx_result.get("data", {}).get("need_draft") or {}

        logger.info(f"[drafting] resume result status={ctx_result.get('status')} existing_draft_keys={list(existing_draft.keys())}")

        # Extract from user message
        extracted = _extractor.extract_all(request.user_message, existing_draft)

        # If schedule_preference still missing, scan recent conversation history for day names
        if not extracted.get("schedule_preference") and not existing_draft.get("schedule_preference"):
            for msg in reversed(request.conversation_history[-6:]):
                if msg.get("role") == "user":
                    sched = _extractor.extract_schedule(msg.get("content", ""))
                    if sched:
                        extracted["schedule_preference"] = sched
                        logger.info(f"[drafting] schedule_preference recovered from history: {sched}")
                        break

        # Renewal detection: if coordinator confirms "same as last year" and we have
        # previous needs, pre-populate all fields except student_count and start_date
        previous_needs = school_ctx.get("previous_needs", [])
        if previous_needs and not any(existing_draft.get(f) for f in ["subjects", "grade_levels"]):
            msg_lower = request.user_message.lower()
            renewal_signals = ["same", "haan", "yes", "ha ", "han ", "theek", "sahi", "bilkul", "correct", "right", "ok", "okay"]
            if any(s in msg_lower for s in renewal_signals):
                # Combine subjects + grades across ALL previous needs (not just first)
                all_subjects: List[str] = []
                all_grades: List[str] = []
                for prev in previous_needs:
                    prev_name = prev.get("name", "")
                    s = prev.get("subjects") or _extractor.extract_subjects(prev_name)
                    g = prev.get("grade_levels") or _extractor.extract_grades(prev_name)
                    all_subjects.extend(s)
                    all_grades.extend(g)

                if not extracted.get("subjects") and all_subjects:
                    extracted["subjects"] = list(dict.fromkeys(all_subjects))  # dedup, preserve order
                if not extracted.get("grade_levels") and all_grades:
                    extracted["grade_levels"] = sorted(list(dict.fromkeys(all_grades)), key=lambda x: int(x))

                # schedule/timeslots from first need (they're usually the same across needs)
                first = previous_needs[0]
                if not extracted.get("schedule_preference"):
                    days = first.get("days", "")
                    freq = first.get("frequency", "")
                    if days:
                        extracted["schedule_preference"] = f"{days} ({freq})" if freq else days

                if not extracted.get("time_slots") and first.get("time_slots"):
                    extracted["time_slots"] = first["time_slots"]

                if not extracted.get("end_date"):
                    extracted["end_date"] = "2027-03-31"

                logger.info(
                    f"[drafting] renewal confirmed — pre-populated from {len(previous_needs)} need(s): "
                    f"subjects={extracted.get('subjects')} grades={extracted.get('grade_levels')} "
                    f"schedule={extracted.get('schedule_preference')}"
                )
        # student_count: delegate to LLM — handles any free-text format
        # (bare number, "X students", "grade 6 - 30 and grade 7 - 20", etc.)
        if not extracted.get("student_count") and not existing_draft.get("student_count"):
            count = await llm_adapter.extract_student_count(request.user_message)
            logger.info(f"[drafting] extract_student_count from '{request.user_message[:50]}' → {count}")
            if count:
                extracted["student_count"] = count

        logger.info(f"[drafting] extracted keys before merge: {list(extracted.keys())}")
        # Strip None/empty from existing_draft before merging so we don't overwrite
        # previously saved values with None (DB returns all columns, even unset ones)
        clean_existing = {k: v for k, v in existing_draft.items()
                          if v is not None and v != "" and not (isinstance(v, list) and len(v) == 0)}
        merged = {**clean_existing, **extracted}
        need_data = {k: v for k, v in merged.items() if v is not None and v != "" and not (isinstance(v, list) and len(v) == 0)}
        coordinator_osid = coord_ctx.get("coordinator_id") or None
        entity_id = school_ctx.get("school_id") or None
        if coordinator_osid:
            need_data["coordinator_osid"] = coordinator_osid
        if entity_id:
            need_data["entity_id"] = entity_id
        logger.info(f"[drafting] saving draft with coordinator_osid={coordinator_osid!r} entity_id={entity_id!r} fields={list(need_data.keys())}")
        save_result = await domain_client.create_or_update_need_draft(
            session_id=session_id,
            need_data=need_data,
        )
        existing_draft = merged

        missing = self._get_missing_fields(existing_draft)
        completion_pct = self._calculate_completion(existing_draft)

        collected = [k for k, v in existing_draft.items() if v is not None and v != "" and not (isinstance(v, list) and len(v) == 0)]
        logger.info(f"[drafting] session={session_id[:8]} collected={collected} missing={missing} completion={completion_pct}%")

        next_state = (
            NeedWorkflowState.PENDING_APPROVAL.value
            if not missing
            else NeedWorkflowState.DRAFTING_NEED.value
        )

        previous_needs = school_ctx.get("previous_needs", [])

        if not missing:
            # All mandatory fields captured — show summary for approval
            msg = await llm_adapter.generate_response(
                stage="pending_approval",
                messages=request.conversation_history,
                user_message=request.user_message,
                coordinator_context=coord_ctx,
                school_context=school_ctx,
                need_draft=existing_draft,
            )
        else:
            # Still collecting — nudge for next missing field, optionally schedule too
            optional_missing = []
            if not existing_draft.get("schedule_preference"):
                optional_missing.append("schedule_preference")
            msg = await llm_adapter.generate_response(
                stage="drafting_need",
                messages=request.conversation_history,
                user_message=request.user_message,
                coordinator_context=coord_ctx,
                school_context=school_ctx,
                need_draft=existing_draft,
                missing_fields=missing + optional_missing,
                previous_needs=previous_needs if not any(existing_draft.get(f) for f in ["subjects", "grade_levels", "student_count"]) else None,
            )

        return self._build_response(
            message=msg,
            next_state=next_state,
            sub=sub,
            session_state=request.session_state,
            confirmed_fields=existing_draft,
            missing_fields=missing,
            completion_pct=completion_pct,
        )

    # ── Stage: PENDING_APPROVAL ───────────────────────────────────────────────

    async def _handle_pending_approval(
        self, request: NeedAgentTurnRequest, sub: Dict
    ) -> NeedAgentTurnResponse:
        session_id = str(request.session_id)
        coord_ctx = sub["coordinator"]
        school_ctx = sub["school"]

        ctx_result = await domain_client.resume_need_context(session_id)
        need_draft: Dict = {}
        need_draft_id: Optional[str] = None
        if ctx_result.get("status") == "success":
            need_draft = ctx_result.get("need_draft") or ctx_result.get("data", {}).get("need_draft") or {}
            need_draft_id = need_draft.get("id")

        lower = request.user_message.lower()

        # Coordinator wants changes
        change_signals = {"no", "wrong", "change", "update", "fix", "actually", "wait", "incorrect"}
        if any(s in lower for s in change_signals):
            msg = await llm_adapter.generate_response(
                stage="drafting_need",
                messages=request.conversation_history,
                user_message=request.user_message,
                coordinator_context=coord_ctx,
                school_context=school_ctx,
                need_draft=need_draft,
            )
            return self._build_response(
                message=msg,
                next_state=NeedWorkflowState.DRAFTING_NEED.value,
                sub=sub,
                session_state=request.session_state,
                confirmed_fields=need_draft,
            )

        # Coordinator confirms
        confirm_signals = {
            "yes", "correct", "confirm", "looks good", "that's right", "perfect",
            "ok", "okay", "approved", "submit", "proceed", "go ahead", "sure",
            "haan", "ha", "theek hai", "sahi hai", "bilkul", "kar do", "bhejo", "send karo",
        }
        if any(s in lower for s in confirm_signals):
            # Submit to Serve Need Service — one need per subject+grade combination
            submit_result: Dict = {}
            serve_need_id: Optional[str] = None
            needs_count: int = 0

            if need_draft_id:
                submit_result = await domain_client.submit_need_for_approval(need_draft_id)
                serve_need_id = submit_result.get("serve_need_id") or submit_result.get("id")
                needs_count = submit_result.get("needs_count", 1)

            ref = f"#{serve_need_id[:8].upper()}" if serve_need_id else "#pending"
            msg = await llm_adapter.generate_response(
                stage="submitted",
                messages=request.conversation_history,
                user_message=request.user_message,
                coordinator_context=coord_ctx,
                school_context=school_ctx,
                need_draft=need_draft,
            )
            # Append reference and count naturally
            if serve_need_id and "reference" not in msg.lower() and ref not in msg:
                count_note = f" {needs_count} teaching needs have been registered." if needs_count > 1 else ""
                msg += f"{count_note} Your reference number is {ref}."

            sub["school"]["serve_need_id"] = serve_need_id
            return self._build_response(
                message=msg,
                next_state=NeedWorkflowState.SUBMITTED.value,
                sub=sub,
                session_state=request.session_state,
                confirmed_fields=need_draft,
                completion_pct=100,
            )

        # Ambiguous reply — show summary again
        msg = await llm_adapter.generate_response(
            stage="pending_approval",
            messages=request.conversation_history,
            user_message=request.user_message,
            coordinator_context=coord_ctx,
            school_context=school_ctx,
            need_draft=need_draft,
        )
        return self._build_response(
            message=msg,
            next_state=NeedWorkflowState.PENDING_APPROVAL.value,
            sub=sub,
            session_state=request.session_state,
            confirmed_fields=need_draft,
        )

    # ── Stage: SUBMITTED ─────────────────────────────────────────────────────

    async def _handle_submitted(
        self, request: NeedAgentTurnRequest, sub: Dict
    ) -> NeedAgentTurnResponse:
        msg = await llm_adapter.generate_response(
            stage="submitted",
            messages=request.conversation_history,
            user_message=request.user_message,
        )
        return self._build_response(
            message=msg,
            next_state=NeedWorkflowState.SUBMITTED.value,
            sub=sub,
            session_state=request.session_state,
            completion_pct=100,
        )

    # ── Stage: REFINEMENT_REQUIRED ────────────────────────────────────────────

    async def _handle_refinement(
        self, request: NeedAgentTurnRequest, sub: Dict
    ) -> NeedAgentTurnResponse:
        msg = await llm_adapter.generate_response(
            stage="refinement_required",
            messages=request.conversation_history,
            user_message=request.user_message,
        )
        return self._build_response(
            message=msg,
            next_state=NeedWorkflowState.DRAFTING_NEED.value,
            sub=sub,
            session_state=request.session_state,
        )

    # ── Stage: PAUSED ────────────────────────────────────────────────────────

    async def _handle_paused(
        self, request: NeedAgentTurnRequest, sub: Dict
    ) -> NeedAgentTurnResponse:
        resume_signals = {"continue", "resume", "ready", "back", "let's go", "start", "hi", "hello"}
        if any(s in request.user_message.lower() for s in resume_signals):
            coord_id = sub["coordinator"].get("coordinator_id")
            school_id = sub["school"].get("school_id")
            if not coord_id:
                next_state = NeedWorkflowState.CAPTURING_PHONE.value
            elif not school_id:
                next_state = NeedWorkflowState.RESOLVING_SCHOOL.value
            else:
                next_state = NeedWorkflowState.DRAFTING_NEED.value
            msg = "Welcome back! Let's pick up where we left off."
        else:
            next_state = NeedWorkflowState.PAUSED.value
            msg = await llm_adapter.generate_response(
                stage="paused",
                messages=request.conversation_history,
                user_message=request.user_message,
            )
        return self._build_response(
            message=msg, next_state=next_state, sub=sub, session_state=request.session_state
        )

    # ── Stage: HUMAN_REVIEW ──────────────────────────────────────────────────

    async def _handle_human_review(
        self, request: NeedAgentTurnRequest, sub: Dict
    ) -> NeedAgentTurnResponse:
        msg = await llm_adapter.generate_response(
            stage="human_review",
            messages=request.conversation_history,
            user_message=request.user_message,
        )
        return self._build_response(
            message=msg,
            next_state=NeedWorkflowState.HUMAN_REVIEW.value,
            sub=sub,
            session_state=request.session_state,
        )

    # ── Fallback ─────────────────────────────────────────────────────────────

    async def _handle_fallback(
        self, request: NeedAgentTurnRequest, sub: Dict
    ) -> NeedAgentTurnResponse:
        logger.warning(f"No handler for stage={request.session_state.stage!r}; using fallback")
        msg = await llm_adapter.generate_response(
            stage="initiated",
            messages=request.conversation_history,
            user_message=request.user_message,
        )
        return self._build_response(
            message=msg,
            next_state=NeedWorkflowState.INITIATED.value,
            sub=sub,
            session_state=request.session_state,
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _build_resolution_messages(
        self, request: NeedAgentTurnRequest, context: Dict
    ) -> List[Dict]:
        """
        Build the message list for a tool-calling loop.
        Includes recent conversation history as user-turn context + current user message.
        """
        messages: List[Dict] = []

        # Add prior conversation as a single user turn for context.
        # Do NOT inject a fake assistant turn — it primes Claude to hallucinate resolution.
        if request.conversation_history:
            recent = request.conversation_history[-4:]
            history_text = "\n".join(
                f"{'Coordinator' if m.get('role') == 'user' else 'eVidyaloka'}: {m.get('content', '')}"
                for m in recent
            )
            messages.append({
                "role": "user",
                "content": f"[Prior conversation for context — do not repeat these exchanges]\n{history_text}\n\n[Latest message from coordinator]",
            })
            messages.append({
                "role": "assistant",
                "content": "Understood. I'll use the prior context and respond to their latest message.",
            })

        messages.append({"role": "user", "content": request.user_message})
        return messages

    def _build_response(
        self,
        message: Optional[str],
        next_state: str,
        sub: Dict,
        session_state: NeedSessionState,
        confirmed_fields: Optional[Dict] = None,
        missing_fields: Optional[List[str]] = None,
        completion_pct: int = 0,
        auto_advance: bool = False,
    ) -> NeedAgentTurnResponse:
        """Build the standard NeedAgentTurnResponse."""
        if auto_advance or message is None:
            message = ""

        # Build the flat confirmed_fields dict the orchestrator exposes via journey_progress.
        # Start with whatever was explicitly passed in (usually the need draft fields),
        # then layer in coordinator and school display names from sub_state.
        flat: Dict[str, Any] = dict(confirmed_fields or {})
        coord = sub.get("coordinator", {})
        school = sub.get("school", {})
        if coord.get("coordinator_name"):
            flat["coordinator_name"] = coord["coordinator_name"]
        if coord.get("phone"):
            flat["coordinator_phone"] = coord["phone"]
        if school.get("school_name"):
            flat["school_name"] = school["school_name"]
        flat["completion_percentage"] = completion_pct

        return NeedAgentTurnResponse(
            assistant_message=message,
            active_agent="need",
            workflow="need_coordination",
            state=next_state,
            sub_state=_dump_sub_state(sub),
            completion_status=self._completion_status(next_state),
            confirmed_fields=flat,
            coordinator_resolved=self._make_coordinator(coord) if coord.get("coordinator_id") else None,
            school_resolved=self._make_school(school) if school.get("school_id") else None,
            missing_fields=missing_fields or [],
            completion_percentage=completion_pct,
            telemetry_events=[],
            handoff_event=None,
        )

    def _completion_status(self, state: str) -> str:
        return {
            NeedWorkflowState.SUBMITTED.value: "submitted",
            NeedWorkflowState.PAUSED.value: "paused",
            NeedWorkflowState.HUMAN_REVIEW.value: "human_review",
            NeedWorkflowState.REJECTED.value: "rejected",
            NeedWorkflowState.FULFILLMENT_HANDOFF_READY.value: "fulfillment_ready",
        }.get(state, "in_progress")

    def _make_coordinator(self, ctx: Dict) -> Optional[Coordinator]:
        try:
            return Coordinator(
                id=ctx.get("coordinator_id"),
                name=ctx.get("coordinator_name") or "Unknown",
                whatsapp_number=ctx.get("phone"),
                email=ctx.get("email"),
                is_verified=ctx.get("is_verified", False),
            )
        except Exception:
            return None

    def _make_school(self, ctx: Dict) -> Optional[School]:
        try:
            return School(
                id=ctx.get("school_id"),
                name=ctx.get("school_name") or "Unknown",
                previous_needs=[
                    n.get("name", "") for n in ctx.get("previous_needs", []) if n
                ],
            )
        except Exception:
            return None

    def _get_missing_fields(self, draft: Dict) -> List[str]:
        return [
            f for f in MANDATORY_NEED_FIELDS
            if draft.get(f) is None or draft.get(f) == "" or (isinstance(draft.get(f), list) and len(draft[f]) == 0)
        ]

    def _calculate_completion(self, draft: Dict) -> int:
        if not draft:
            return 0
        filled = sum(
            1 for f in MANDATORY_NEED_FIELDS
            if draft.get(f) is not None and draft.get(f) != "" and not (isinstance(draft.get(f), list) and len(draft[f]) == 0)
        )
        return round((filled / len(MANDATORY_NEED_FIELDS)) * 100)


# ── Domain client wrappers (thin pass-through) ────────────────────────────────
# These keep domain_client.py interface stable and centralise the mapping.

class _DomainClientAdapter:
    """
    Thin wrapper exposing the method signatures used by stage handlers.
    Delegates to _mcp_client (the real DomainClient singleton) to avoid
    the circular-reference that would result from reassigning the module-level name.
    """

    async def resolve_coordinator_identity(
        self,
        whatsapp_number: Optional[str] = None,
        email: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Dict:
        return await _mcp_client.resolve_coordinator_identity(
            whatsapp_number=whatsapp_number, email=email
        )

    async def create_coordinator(
        self, name: str, whatsapp_number: Optional[str] = None, email: Optional[str] = None
    ) -> Dict:
        return await _mcp_client.create_coordinator(
            name=name, whatsapp_number=whatsapp_number, email=email
        )

    async def resolve_school_context(
        self,
        coordinator_id: Optional[str] = None,
        school_hint: Optional[str] = None,
    ) -> Dict:
        return await _mcp_client.resolve_school_context(
            coordinator_id=coordinator_id, school_hint=school_hint
        )

    async def map_coordinator_to_school(self, coordinator_id: str, school_id: str) -> Dict:
        return await _mcp_client.map_coordinator_to_school(
            coordinator_id=coordinator_id, school_id=school_id
        )

    async def create_basic_school_context(
        self,
        name: str,
        location: str,
        contact_number: Optional[str] = None,
        coordinator_id: Optional[str] = None,
    ) -> Dict:
        return await _mcp_client.create_basic_school_context(
            name=name, location=location, contact_number=contact_number
        )

    async def fetch_previous_need_context(self, school_id: str) -> Dict:
        return await _mcp_client.fetch_previous_need_context(school_id=school_id)

    async def resume_need_context(self, session_id: str) -> Dict:
        return await _mcp_client.resume_need_context(session_id=session_id)

    async def create_or_update_need_draft(self, session_id: str, need_data: Dict) -> Dict:
        return await _mcp_client.create_or_update_need_draft(
            session_id=session_id, need_data=need_data
        )

    async def submit_need_for_approval(self, need_id: str) -> Dict:
        return await _mcp_client.submit_need_for_approval(need_id=need_id)


# Stage handlers use this adapter, not the raw _mcp_client
domain_client = _DomainClientAdapter()

# Singleton
need_agent_service = NeedAgentService()
