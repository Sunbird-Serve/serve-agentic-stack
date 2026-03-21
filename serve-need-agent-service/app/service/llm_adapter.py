"""
SERVE Need Agent Service - LLM Adapter (L3.5)

Two modes of operation:
  1. Tool-calling loop (L3.5)  — RESOLVING_COORDINATOR and RESOLVING_SCHOOL stages.
     Claude is given tool definitions; it calls tools autonomously, collects results,
     and only produces a user-facing message when it needs input or finishes resolving.

  2. Plain text generation      — DRAFTING_NEED, PENDING_APPROVAL, and other stages.
     Claude receives a rich system prompt with captured context and conversation history,
     and replies with a single conversational message.

Tool execution is handled by callables passed in from need_logic.py so the adapter
has no direct dependency on domain_client.
"""
import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Tool definitions ──────────────────────────────────────────────────────────

COORDINATOR_TOOLS: List[Dict] = [
    {
        "name": "lookup_coordinator_by_phone",
        "description": (
            "Look up the coordinator in Serve Registry using their phone/WhatsApp number. "
            "Returns status='linked' with coordinator data if found, or status='unlinked' if not."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "Phone number in any format"},
            },
            "required": ["phone"],
        },
    },
    {
        "name": "lookup_coordinator_by_email",
        "description": (
            "Look up the coordinator in Serve Registry using their email address. "
            "More reliable than phone lookup. Use this when phone lookup fails or "
            "when the coordinator provides their email."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Email address"},
            },
            "required": ["email"],
        },
    },
    {
        "name": "register_new_coordinator",
        "description": (
            "Register a new coordinator in Serve Registry. Use this only after confirming "
            "that the coordinator is genuinely new (not found by phone or email)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Full name"},
                "phone": {"type": "string", "description": "Phone number"},
                "email": {"type": "string", "description": "Email address"},
            },
            "required": ["name"],
        },
    },
]

SCHOOL_TOOLS: List[Dict] = [
    {
        "name": "get_schools_for_coordinator",
        "description": (
            "Fetch all schools/entities already linked to this coordinator in Serve Need Service. "
            "Use this first when coordinator_id is available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "coordinator_id": {"type": "string", "description": "Serve Registry coordinator osid"},
            },
            "required": ["coordinator_id"],
        },
    },
    {
        "name": "search_school",
        "description": (
            "Search for a school by UDISE code or school name. "
            "UDISE codes are part of the entity name in the system, so searching by UDISE code "
            "as a text hint works. Use for unlinked coordinators or when linked schools are wrong."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hint": {
                    "type": "string",
                    "description": "UDISE code (11-digit number) or school name or partial name",
                },
            },
            "required": ["hint"],
        },
    },
    {
        "name": "fetch_previous_needs",
        "description": (
            "Fetch previous teaching needs for a school. Call this when the school is identified "
            "to check whether this is a renewal of existing support."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "school_id": {"type": "string", "description": "Serve Need Service entity ID"},
            },
            "required": ["school_id"],
        },
    },
    {
        "name": "link_coordinator_to_school",
        "description": (
            "Link this coordinator to an existing school in Serve Need Service. "
            "Call this when coordinator confirmed they belong to a school found by search."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "coordinator_id": {"type": "string"},
                "school_id": {"type": "string"},
            },
            "required": ["coordinator_id", "school_id"],
        },
    },
    {
        "name": "create_new_school",
        "description": (
            "Create a new school/entity in Serve Need Service. Use only after confirming "
            "the coordinator's school genuinely does not exist in the system."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "School name"},
                "district": {"type": "string", "description": "District"},
                "state": {"type": "string", "description": "State"},
                "contact_number": {"type": "string", "description": "Contact number"},
                "coordinator_id": {
                    "type": "string",
                    "description": "Auto-link this coordinator to the new school",
                },
            },
            "required": ["name"],
        },
    },
]


# ── eVidyaloka context ────────────────────────────────────────────────────────

_EVID_CONTEXT = """
You are the eVidyaloka Need Coordination Assistant.
eVidyaloka connects volunteer teachers with rural schools across India that need teaching support.

Communication guidelines:
- Professional yet warm — coordinators are partners in the mission
- Clear and efficient — they are busy people
- Respectful of their local knowledge
- NEVER use technical jargon: no "workflow", "agent", "MCP", "osid", "entity", "system"
- Focus on children's educational needs
- Keep responses to 2-3 sentences; ask only one question at a time
"""

# ── Stage prompts (plain text generation) ────────────────────────────────────

_STAGE_PROMPTS: Dict[str, str] = {
    "initiated": (
        "Warmly greet the coordinator and ask for their phone number to get started. "
        "Explain it helps us link them to their school quickly."
    ),
    "capturing_phone": (
        "The coordinator is providing their phone number. "
        "If a valid phone number is present in their message, acknowledge it warmly and let them know "
        "you are looking them up. If no phone number is found, politely ask again."
    ),
    "resolving_coordinator": (
        "You are verifying the coordinator's identity. "
        "Guide the coordinator naturally — do not mention system lookups or technical steps."
    ),
    "resolving_school": (
        "You are identifying which school this coordinator is coordinating for. "
        "Be conversational. If the school has previous support history, mention it naturally."
    ),
    "drafting_need": (
        "STAGE: Capturing the Need\n"
        "Collect the specific educational need one question at a time:\n"
        "- Subjects (mathematics, science, english, etc.)\n"
        "- Grade levels (1-12)\n"
        "- Number of students\n"
        "- Time slots for online classes\n"
        "- Start date\n"
        "- Duration (weeks)\n\n"
        "Acknowledge what the coordinator has already shared before asking the next question. "
        "Be flexible — 'math for 5th graders' gives you both subject and grade."
    ),
    "pending_approval": (
        "STAGE: Review & Confirmation\n"
        "Summarise the complete need clearly and ask the coordinator to confirm:\n"
        "- School name\n"
        "- Subjects\n"
        "- Grades\n"
        "- Number of students\n"
        "- Time slots\n"
        "- Start date\n"
        "- Duration\n\n"
        "Ask if anything needs to be changed before we proceed."
    ),
    "submitted": (
        "The need has been successfully registered. "
        "Thank the coordinator warmly. Mention the reference ID. "
        "Let them know the team will start matching volunteers and will be in touch."
    ),
    "approved": (
        "The need has been confirmed. Thank the coordinator. "
        "Let them know matching will begin shortly."
    ),
    "paused": (
        "The coordinator wants to pause. Acknowledge warmly, confirm their progress is saved, "
        "and let them know they can return at any time."
    ),
    "refinement_required": (
        "Some details need clarification. Explain what needs to be addressed clearly "
        "and help the coordinator provide the updated information."
    ),
    "human_review": (
        "Something needs human attention. Explain that someone from the eVidyaloka team "
        "will review and follow up shortly. Be reassuring."
    ),
}


# ── LLM Adapter ──────────────────────────────────────────────────────────────

class NeedLLMAdapter:
    """
    LLM adapter for the Need Agent.

    Uses Anthropic's native tool-use API for the resolution stages (L3.5),
    and plain text generation for all other stages.
    """

    def __init__(self) -> None:
        self._api_key: Optional[str] = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("EMERGENT_LLM_KEY")
        self._model: str = os.environ.get("LLM_MODEL", "claude-sonnet-4-5-20250929")
        self._client = None  # lazy

    def _get_client(self):
        if self._client is None:
            if not self._api_key:
                return None
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
            except ImportError:
                logger.warning("anthropic package not installed — LLM features degraded")
        return self._client

    # ── Tool-calling loop ─────────────────────────────────────────────────────

    async def run_tool_loop(
        self,
        system_prompt: str,
        initial_messages: List[Dict],
        tools: List[Dict],
        tool_executor: Callable[[str, Dict], Any],
        max_iterations: int = 8,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Run a Claude tool-calling loop for one user turn.

        Claude calls tools autonomously until it produces a plain-text response
        (the message to send to the coordinator) or max_iterations is reached.

        Returns:
            (response_text_for_coordinator, collected_tool_results)
            collected_tool_results is a flat dict of tool_name → last_result
            so the caller can check what was resolved.
        """
        client = self._get_client()
        if client is None:
            return self._tool_loop_fallback(initial_messages), {}

        messages = list(initial_messages)
        collected: Dict[str, Any] = {}

        for iteration in range(max_iterations):
            try:
                response = await client.messages.create(
                    model=self._model,
                    max_tokens=1024,
                    system=system_prompt,
                    messages=messages,
                    tools=tools,
                )
            except Exception as exc:
                logger.error(f"Claude API error in tool loop (iter {iteration}): {exc}")
                return self._tool_loop_fallback(messages), collected

            tool_uses = [b for b in response.content if b.type == "tool_use"]

            if not tool_uses:
                # Claude produced a text response — that is the message for the coordinator
                text = next(
                    (b.text for b in response.content if hasattr(b, "text") and b.text),
                    "I'm here to help. Could you provide a bit more information?",
                )
                return text, collected

            # Claude wants to call tools — execute them all, collect results
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tu in tool_uses:
                try:
                    result = await tool_executor(tu.name, tu.input)
                except Exception as exc:
                    logger.error(f"Tool executor error for {tu.name!r}: {exc}")
                    result = {"status": "error", "error": str(exc)}

                collected[tu.name] = result
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result),
                })

            messages.append({"role": "user", "content": tool_results})

        # Exhausted iterations — ask Claude for a plain response with current context
        try:
            final = await client.messages.create(
                model=self._model,
                max_tokens=512,
                system=system_prompt + "\n\nYou have exhausted tool calls. Give the coordinator a clear next step.",
                messages=messages,
            )
            text = next(
                (b.text for b in final.content if hasattr(b, "text") and b.text),
                "I need a moment to look into this. Could you confirm your details?",
            )
            return text, collected
        except Exception:
            return "I'm having trouble accessing our records right now. Could you try again shortly?", collected

    def _tool_loop_fallback(self, messages: List[Dict]) -> str:
        """Fallback message when no API client is available."""
        # Infer what stage we're probably at from the last user message
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user" and isinstance(m.get("content"), str)),
            "",
        )
        if "@" in last_user:
            return "Thank you! Let me look up your details."
        if any(c.isdigit() for c in last_user):
            return "Got it! Let me check our records."
        return "Thank you. Could you share your school's UDISE code or name so I can find it?"

    # ── Coordinator resolution (L3.5) ─────────────────────────────────────────

    def build_coordinator_system_prompt(
        self,
        resolution_ctx: Dict[str, Any],
    ) -> str:
        """System prompt for RESOLVING_COORDINATOR tool-calling loop."""
        ctx_lines = []
        if resolution_ctx.get("phone"):
            tried = " (already looked up — not found)" if resolution_ctx.get("phone_tried") else " (not yet looked up)"
            ctx_lines.append(f"- Phone number: {resolution_ctx['phone']}{tried}")
        if resolution_ctx.get("email"):
            tried = " (already looked up — not found)" if resolution_ctx.get("email_tried") else " (not yet looked up)"
            ctx_lines.append(f"- Email: {resolution_ctx['email']}{tried}")
        if resolution_ctx.get("name"):
            ctx_lines.append(f"- Name provided: {resolution_ctx['name']}")
        if resolution_ctx.get("coordinator_id"):
            ctx_lines.append(f"- Coordinator already resolved: ID={resolution_ctx['coordinator_id']}, name={resolution_ctx.get('coordinator_name')}")

        ctx_block = "\n".join(ctx_lines) if ctx_lines else "  (none yet)"

        return f"""{_EVID_CONTEXT}

CURRENT STAGE: Coordinator Identity Resolution

What you know so far:
{ctx_block}

Your task:
1. If coordinator is already resolved (coordinator_id known), skip all lookups and respond warmly.
2. If phone is available and NOT yet tried, call lookup_coordinator_by_phone.
3. If phone lookup returned 'unlinked', ask the coordinator for their email address.
4. If email is available and NOT yet tried, call lookup_coordinator_by_email.
5. If email lookup returned 'linked', respond warmly confirming their identity.
6. If email lookup returned 'unlinked' AND coordinator has confirmed they are new, ask for their name then call register_new_coordinator.
7. If you are waiting for the coordinator to provide their email or name, ask for it conversationally.

Important:
- Do not repeat lookups already tried.
- Do not tell the coordinator you are "looking them up" or mention any system.
- After any successful lookup, confirm their name naturally: "I see you're [Name] — great!"
- If genuinely unsure (no phone, no email, coordinator seems confused), respond warmly and ask for email.
"""

    # ── School resolution (L3.5) ──────────────────────────────────────────────

    def build_school_system_prompt(
        self,
        coordinator_ctx: Dict[str, Any],
        resolution_ctx: Dict[str, Any],
    ) -> str:
        """System prompt for RESOLVING_SCHOOL tool-calling loop."""
        coord_name = coordinator_ctx.get("coordinator_name") or "the coordinator"
        coord_id = coordinator_ctx.get("coordinator_id", "")

        ctx_lines = []
        if resolution_ctx.get("school_id"):
            ctx_lines.append(f"- School already resolved: ID={resolution_ctx['school_id']}, name={resolution_ctx.get('school_name')}")
        if resolution_ctx.get("udise_hint"):
            ctx_lines.append(f"- UDISE/hint provided: {resolution_ctx['udise_hint']}")
        if resolution_ctx.get("linked_schools_checked"):
            ctx_lines.append("- Linked schools already fetched (see previous tool results)")
        prev = resolution_ctx.get("previous_needs", [])
        if prev:
            subjects = ", ".join(p.get("subjects", "") or p.get("name", "") for p in prev[:3])
            ctx_lines.append(f"- Previous needs found: {subjects}")

        ctx_block = "\n".join(ctx_lines) if ctx_lines else "  (none yet)"

        return f"""{_EVID_CONTEXT}

CURRENT STAGE: School Context Resolution
Coordinator: {coord_name} (ID: {coord_id or 'not yet in registry'})

What you know so far:
{ctx_block}

Your task:
1. If school is already resolved (school_id known) AND previous needs fetched — respond with that context.
2. If coordinator_id is available and linked schools NOT yet checked, call get_schools_for_coordinator first.
3. If coordinator has one linked school, confirm it with them naturally and call fetch_previous_needs.
4. If coordinator has multiple linked schools, list them and ask which one this need is for.
5. If no linked schools (or coordinator is new/unlinked), ask: "Do you know your school's UDISE code?"
   - If they provide a UDISE code, call search_school with it.
   - If they say they don't know it, ask for the school name and call search_school with the name.
6. If search returns one match, confirm with coordinator and call link_coordinator_to_school + fetch_previous_needs.
7. If search returns multiple matches, present the top options and ask the coordinator to confirm.
8. If no match is found, confirm the school is new, gather name + district + state, call create_new_school.
9. Once school is resolved and previous needs are fetched (or school is new), present the context to the coordinator:
   - For existing schools with previous needs: "I can see [School] had support for [subjects] for Grades [X-Y] last year. Is this year's need similar, or are there changes?"
   - For new schools: move straight to need capture.

Important:
- Do not mention system IDs or technical terms.
- School name in conversation = friendly name, not internal ID.
- If previous needs exist, always surface them to offer renewal.
"""

    # ── Plain text generation ─────────────────────────────────────────────────

    async def generate_response(
        self,
        stage: str,
        messages: List[Dict[str, str]],
        user_message: str,
        coordinator_context: Optional[Dict] = None,
        school_context: Optional[Dict] = None,
        need_draft: Optional[Dict] = None,
        missing_fields: Optional[List[str]] = None,
        previous_needs: Optional[List[Dict]] = None,
    ) -> str:
        """
        Generate a plain conversational response for non-resolution stages.
        Falls back gracefully if no API key is configured.
        """
        client = self._get_client()
        if client is None:
            return self._get_fallback_response(stage, missing_fields)

        system = self._build_text_prompt(
            stage=stage,
            coordinator_context=coordinator_context,
            school_context=school_context,
            need_draft=need_draft,
            missing_fields=missing_fields,
            previous_needs=previous_needs,
        )

        # Build conversation context (last 6 messages)
        convo = ""
        for msg in messages[-6:]:
            role = "Coordinator" if msg.get("role") == "user" else "eVidyaloka"
            convo += f"{role}: {msg.get('content', '')}\n"
        full_msg = f"{convo}\nCoordinator: {user_message}" if convo else user_message

        try:
            response = await client.messages.create(
                model=self._model,
                max_tokens=512,
                system=system,
                messages=[{"role": "user", "content": full_msg}],
            )
            return next(
                (b.text for b in response.content if hasattr(b, "text") and b.text),
                self._get_fallback_response(stage, missing_fields),
            )
        except Exception as exc:
            logger.error(f"LLM text generation error (stage={stage}): {exc}")
            return self._get_fallback_response(stage, missing_fields)

    def _build_text_prompt(
        self,
        stage: str,
        coordinator_context: Optional[Dict],
        school_context: Optional[Dict],
        need_draft: Optional[Dict],
        missing_fields: Optional[List[str]],
        previous_needs: Optional[List[Dict]],
    ) -> str:
        stage_instr = _STAGE_PROMPTS.get(stage, _STAGE_PROMPTS["initiated"])
        prompt = f"{_EVID_CONTEXT}\n\n{stage_instr}"

        if coordinator_context:
            name = coordinator_context.get("coordinator_name") or coordinator_context.get("name", "")
            if name:
                prompt += f"\n\nCOORDINATOR: {name}"

        if school_context:
            sname = school_context.get("school_name") or school_context.get("name", "")
            sloc = school_context.get("location") or school_context.get("district", "")
            prompt += f"\n\nSCHOOL: {sname}" + (f", {sloc}" if sloc else "")

        if previous_needs:
            prev_desc = []
            for p in previous_needs[:2]:
                subjects = p.get("subjects") or []
                if isinstance(subjects, str):
                    subjects = [subjects]
                name_str = p.get("name", "")
                desc = ", ".join(subjects) if subjects else name_str
                if desc:
                    prev_desc.append(desc)
            if prev_desc:
                prompt += f"\n\nPREVIOUS NEEDS: {'; '.join(prev_desc)}"

        if need_draft:
            captured = []
            for key, label in [
                ("subjects", "Subjects"),
                ("grade_levels", "Grades"),
                ("student_count", "Students"),
                ("time_slots", "Time slots"),
                ("start_date", "Start date"),
                ("duration_weeks", "Duration (weeks)"),
            ]:
                val = need_draft.get(key)
                if val:
                    display = ", ".join(str(v) for v in val) if isinstance(val, list) else str(val)
                    captured.append(f"{label}: {display}")
            if captured:
                prompt += "\n\nCAPTURED SO FAR:\n" + "\n".join(captured)

        if missing_fields:
            field_labels = {
                "subjects": "what subjects students need help with",
                "grade_levels": "which grade levels",
                "student_count": "how many students",
                "time_slots": "what time slots work for classes",
                "start_date": "when they want to start",
                "duration_weeks": "how many weeks of support",
            }
            readable = [field_labels.get(f, f) for f in missing_fields[:2]]
            prompt += f"\n\nSTILL NEEDED: {', '.join(readable)}. Ask about one naturally."

        return prompt

    def _get_fallback_response(self, stage: str, missing_fields: Optional[List[str]] = None) -> str:
        fallbacks = {
            "initiated": "Hello! Welcome to eVidyaloka. I'm here to help you register teaching support for your school. Could you share your phone number to get started?",
            "capturing_phone": "Could you share your phone number? It helps us quickly link you to your school.",
            "resolving_coordinator": "Could you share your email address so I can look up your details?",
            "resolving_school": "Could you share your school's UDISE code? It's an 11-digit number, or you can share the school name.",
            "drafting_need": "What subjects do the students need help with?",
            "pending_approval": "Let me summarise the details we've captured. Does everything look correct?",
            "submitted": "Your need has been successfully registered! We'll start matching volunteers and keep you updated.",
            "approved": "Your need has been confirmed. We'll begin matching volunteers shortly!",
            "paused": "No problem! Your progress has been saved. Message us when you're ready to continue.",
            "refinement_required": "Could you help us clarify a few details?",
            "human_review": "Let me have someone from our team follow up with you shortly.",
        }
        base = fallbacks.get(stage, fallbacks["initiated"])
        if stage == "drafting_need" and missing_fields:
            field_prompts = {
                "subjects": "What subjects do the students need help with?",
                "grade_levels": "Which grade levels need support?",
                "student_count": "Approximately how many students will participate?",
                "time_slots": "What time slots work best for online classes?",
                "start_date": "When would you like the support to start?",
                "duration_weeks": "For how many weeks would you like the support?",
            }
            base = field_prompts.get(missing_fields[0], base)
        return base


# Singleton
llm_adapter = NeedLLMAdapter()
