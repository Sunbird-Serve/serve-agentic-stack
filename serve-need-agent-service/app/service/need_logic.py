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
        m = self.STUDENT_RE.search(text)
        if m:
            count = int(m.group(1))
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
        match = self.DATE_RE.search(text)
        if match:
            d, mo, y = match.groups()
            if len(y) == 2:
                y = f"20{y}"
            try:
                return date(int(y), int(mo), int(d)).isoformat()
            except ValueError:
                pass
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

        count = self.extract_student_count(text)
        if count is not None:
            extracted["student_count"] = count

        slots = self.extract_time_slots(text)
        if slots:
            merged = list(set(existing.get("time_slots", []) + slots))
            extracted["time_slots"] = merged

        start = self.extract_start_date(text)
        if start:
            extracted["start_date"] = start

        dur = self.extract_duration(text)
        if dur is not None:
            extracted["duration_weeks"] = dur

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
            NeedWorkflowState.RESOLVING_SCHOOL.value:       self._handle_resolving_school,
            NeedWorkflowState.DRAFTING_NEED.value:          self._handle_drafting_need,
            NeedWorkflowState.PENDING_APPROVAL.value:       self._handle_pending_approval,
            NeedWorkflowState.SUBMITTED.value:              self._handle_submitted,
            NeedWorkflowState.REFINEMENT_REQUIRED.value:    self._handle_refinement,
            NeedWorkflowState.PAUSED.value:                 self._handle_paused,
            NeedWorkflowState.HUMAN_REVIEW.value:           self._handle_human_review,
        }

        handler = dispatch.get(stage, self._handle_fallback)
        return await handler(request, sub)

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
            # Phone already known — skip CAPTURING_PHONE regardless of channel
            sub["coordinator"]["phone"] = phone
            next_state = NeedWorkflowState.RESOLVING_COORDINATOR.value
            msg = await llm_adapter.generate_response(
                stage="initiated",
                messages=[],
                user_message=request.user_message,
            )
        elif channel == "whatsapp":
            # WhatsApp but no phone in metadata (shouldn't normally happen)
            sub["coordinator"]["phone"] = None
            next_state = NeedWorkflowState.RESOLVING_COORDINATOR.value
            msg = await llm_adapter.generate_response(
                stage="initiated",
                messages=[],
                user_message=request.user_message,
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

        # Already resolved — skip to school
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

        # Build tool executor
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
            logger.warning(f"Unknown tool in coordinator loop: {tool_name}")
            return {"status": "error", "error": f"Unknown tool: {tool_name}"}

        # Build messages for tool loop
        initial_messages = self._build_resolution_messages(request, coord_ctx)

        system_prompt = llm_adapter.build_coordinator_system_prompt(coord_ctx)
        msg, tool_results = await llm_adapter.run_tool_loop(
            system_prompt=system_prompt,
            initial_messages=initial_messages,
            tools=llm_adapter.COORDINATOR_TOOLS,
            tool_executor=coordinator_tool_executor,
        )

        # Check resolution outcome from tool results
        for _tool_name, result in tool_results.items():
            if result.get("status") == "linked":
                coordinator = result.get("coordinator") or {}
                coord_ctx["coordinator_id"] = coordinator.get("id")
                coord_ctx["coordinator_name"] = coordinator.get("name") or coord_ctx.get("name")
                coord_ctx["is_verified"] = coordinator.get("is_verified", False)
                break
            if result.get("id"):  # create_coordinator result
                coord_ctx["coordinator_id"] = result.get("id")
                coord_ctx["coordinator_name"] = result.get("name") or coord_ctx.get("name")
                coord_ctx["is_verified"] = False
                break

        sub["coordinator"] = coord_ctx
        resolved = bool(coord_ctx.get("coordinator_id"))
        next_state = (
            NeedWorkflowState.RESOLVING_SCHOOL.value
            if resolved
            else NeedWorkflowState.RESOLVING_COORDINATOR.value
        )

        return self._build_response(
            message=msg,
            next_state=next_state,
            sub=sub,
            session_state=request.session_state,
            confirmed_fields={
                "coordinator_name": coord_ctx.get("coordinator_name"),
                "coordinator_id": coord_ctx.get("coordinator_id"),
            } if resolved else {},
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
        )

        # Extract resolution outcome from tool results
        for tool_name, result in tool_results.items():
            school = result.get("school") or {}
            if school.get("id") and tool_name in (
                "get_schools_for_coordinator", "search_school",
                "create_new_school", "link_coordinator_to_school",
            ):
                if result.get("status") in ("existing", "success") or school.get("id"):
                    school_ctx["school_id"] = school.get("id")
                    school_ctx["school_name"] = school.get("name")
                    break
            # create_new_school may return entity directly
            if tool_name == "create_new_school" and result.get("id"):
                school_ctx["school_id"] = result.get("id")
                school_ctx["school_name"] = result.get("name")
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
        if ctx_result.get("status") == "success" and ctx_result.get("data"):
            existing_draft = ctx_result["data"].get("need_draft") or {}

        # Extract from user message
        extracted = _extractor.extract_all(request.user_message, existing_draft)
        if extracted:
            merged = {**existing_draft, **extracted}
            save_args = {
                "session_id": session_id,
                "coordinator_osid": coord_ctx.get("coordinator_id") or "",
                "entity_id": school_ctx.get("school_id") or "",
            }
            save_args.update({k: v for k, v in merged.items() if v})
            await domain_client.create_or_update_need_draft(**save_args)
            existing_draft = merged

        missing = self._get_missing_fields(existing_draft)
        completion_pct = self._calculate_completion(existing_draft)

        next_state = (
            NeedWorkflowState.PENDING_APPROVAL.value
            if not missing
            else NeedWorkflowState.DRAFTING_NEED.value
        )

        previous_needs = school_ctx.get("previous_needs", [])
        msg = await llm_adapter.generate_response(
            stage="drafting_need",
            messages=request.conversation_history,
            user_message=request.user_message,
            coordinator_context=coord_ctx,
            school_context=school_ctx,
            need_draft=existing_draft,
            missing_fields=missing,
            previous_needs=previous_needs if existing_draft == {} else None,
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
        if ctx_result.get("status") == "success" and ctx_result.get("data"):
            data = ctx_result["data"]
            need_draft = data.get("need_draft") or {}
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
        }
        if any(s in lower for s in confirm_signals):
            # Submit to Serve Need Service
            submit_result: Dict = {}
            serve_need_id: Optional[str] = None

            if need_draft_id:
                submit_result = await domain_client.submit_need_for_approval(need_draft_id)
                serve_need_id = submit_result.get("serve_need_id") or submit_result.get("id")

            ref = f"#{serve_need_id[:8].upper()}" if serve_need_id else "#pending"
            msg = await llm_adapter.generate_response(
                stage="submitted",
                messages=request.conversation_history,
                user_message=request.user_message,
                coordinator_context=coord_ctx,
                school_context=school_ctx,
                need_draft=need_draft,
            )
            # Append reference number naturally
            if serve_need_id and "reference" not in msg.lower() and ref not in msg:
                msg += f" Your reference number is {ref}."

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
        Includes recent conversation history (as a context summary) + current user message.
        """
        messages: List[Dict] = []

        # Add prior conversation as a single assistant turn for context
        if request.conversation_history:
            recent = request.conversation_history[-4:]
            history_text = "\n".join(
                f"{'Coordinator' if m.get('role') == 'user' else 'eVidyaloka'}: {m.get('content', '')}"
                for m in recent
            )
            messages.append({
                "role": "user",
                "content": f"[Prior conversation]\n{history_text}",
            })
            messages.append({
                "role": "assistant",
                "content": "I have the conversation context. What's their latest message?",
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
            if not draft.get(f) or (isinstance(draft[f], list) and not draft[f])
        ]

    def _calculate_completion(self, draft: Dict) -> int:
        if not draft:
            return 0
        filled = sum(
            1 for f in MANDATORY_NEED_FIELDS
            if draft.get(f) and (not isinstance(draft[f], list) or draft[f])
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

    async def create_or_update_need_draft(self, session_id: str, **kwargs) -> Dict:
        return await _mcp_client.create_or_update_need_draft(
            session_id=session_id, need_data=kwargs
        )

    async def submit_need_for_approval(self, need_id: str) -> Dict:
        return await _mcp_client.submit_need_for_approval(need_id=need_id)


# Stage handlers use this adapter, not the raw _mcp_client
domain_client = _DomainClientAdapter()

# Singleton
need_agent_service = NeedAgentService()
