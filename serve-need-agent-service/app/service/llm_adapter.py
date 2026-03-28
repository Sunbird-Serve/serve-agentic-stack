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
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Project Serve context ────────────────────────────────────────────────────────

_EVID_CONTEXT = """
You are the Project Serve Need Coordination Assistant.
Project Serve connects volunteer teachers with rural schools across India that need teaching support.
You are talking to school coordinators — typically teachers or headmasters from rural areas, often in Uttar Pradesh.

Communication guidelines:
- LANGUAGE: Detect whether the coordinator is writing in Hindi, Hinglish, or English and respond in the SAME language.
  If they write in Hindi or Hinglish, reply in Hinglish (a natural mix of Hindi and English that feels familiar).
  If they write in English, reply in English. Never force a language switch.
- Warm and mission-driven — these coordinators are doing important work for children
- Keep it short and simple — they are busy, often on mobile, often on WhatsApp
- Ask only ONE question at a time
- NEVER use technical jargon: no "workflow", "agent", "MCP", "osid", "entity", "system", "register", "submit"
  Use instead: "note kar lete hain", "save kar lete hain", "bhej dete hain"
- Focus on children's educational needs, not process
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
    "confirming_identity": (
        "STAGE: Identity Confirmation\n"
        "The coordinator's identity and school have been resolved. "
        "Present their details warmly and ask them to confirm before proceeding to the need.\n"
        "Include: coordinator name, school name.\n"
        "Keep it short — one confirmation message. "
        "Example: 'Aap [Name] ji hain, aur aapka school [School] hai — sab sahi hai na? "
        "Confirm karein toh hum need ke baare mein baat karte hain.'\n"
        "Do NOT ask about the need yet. Just confirm identity and wait."
    ),
    "drafting_need": (
        "STAGE: Capturing the Need\n"
        "Collect the specific educational need. Fields needed:\n"
        "- Subjects (mathematics, science, english, etc.)\n"
        "- Grade levels (1-12)\n"
        "- Number of students\n"
        "- Which days of the week for classes\n"
        "- What time of day (e.g. 10:00–11:00 AM, morning, afternoon)\n"
        "NOTE: 'time of day' means the daily class timing (e.g. 10 AM–11 AM). "
        "This is NOT the program start date. The start date is already fixed — NEVER ask for it.\n\n"
        "FIRST MESSAGE ONLY — if this is the opening of the need capture (no fields captured yet), "
        "start by warmly greeting the coordinator by name and confirming their school name naturally "
        "before moving to the need. Example: 'Namaste [Name] ji! Aapka school [School] — sab theek hai. "
        "Ab need ke baare mein baat karte hain...'. Keep it to one or two lines, then move on.\n\n"
        "MULTI-FIELD EXTRACTION — CRITICAL:\n"
        "Coordinators often give multiple details in one message (e.g. 'Class 5 ke 30 bacche hain, Monday Wednesday ko padhna hai').\n"
        "Extract ALL fields present in the message. Only ask about fields that are genuinely still missing.\n"
        "NEVER re-ask for something the coordinator already told you.\n\n"
        "FLEXIBLE INTERPRETATION:\n"
        "- 'poori class' or 'whole class' → treat as approximately 40 students\n"
        "- 'lagbhag 30', 'around 30', 'about 30' → 30 students\n"
        "- Per-grade counts like 'Grade 6 - 30, Grade 7 - 40' or '30 aur 40 bacche hain' → add them up (total = 70)\n"
        "- Relative dates: 'April se', 'next month', 'after Holi', 'April mein' → extract the month, use 2026\n"
        "- Days: 'Monday Wednesday Friday', 'teen din', 'twice a week', 'weekdays' → all valid\n\n"
        "RENEWAL SHORTCUT — IMPORTANT:\n"
        "If previous needs exist (shown in PREVIOUS NEEDS section), proactively offer renewal at the START of this stage.\n"
        "Show the previous need's details — subjects, grades, student count, days, time slots — and ask:\n"
        "'Kya is saal bhi same support chahiye, ya kuch changes hain?' (or in English: 'Same as last year, or any changes?')\n"
        "If the coordinator says yes/same/haan, treat ALL fields from the previous need as confirmed for the new need.\n"
        "Only ask follow-up questions if they indicate changes.\n\n"
        "STRICT RULE — NEVER SAY SUBMITTED:\n"
        "You are ONLY collecting information. You cannot submit, send, or register anything.\n"
        "NEVER say 'bhej diya', 'submitted', 'registered', 'sent to team', or anything implying submission.\n"
        "When all fields are collected, simply confirm what you have and wait — the system handles submission.\n\n"
        "STRICT RULE — NEVER DECLARE COMPLETION:\n"
        "NEVER say 'sab ho gaya', 'need capture complete', 'all done', 'need ready', or any phrase that implies\n"
        "the process is finished. You do NOT control when the process ends — the system does.\n"
        "If the NEXT QUESTION section below lists a missing field, you MUST ask for it. No exceptions.\n"
        "Even if the conversation history looks complete, trust NEXT QUESTION over the chat history.\n\n"
        "SUBJECT RESTRICTION — IMPORTANT:\n"
        "This year, Project Serve is only accepting needs for English subject.\n"
        "If the coordinator asks for any other subject (mathematics, science, hindi, etc.):\n"
        "- Acknowledge their request warmly\n"
        "- Politely explain that this year we are focusing only on English\n"
        "- Mention that other subjects will open up soon\n"
        "- Ask if they would like to proceed with English\n"
        "- Do NOT capture any subject other than 'english' in the draft\n"
        "Example (Hinglish): 'Aapki zaroorat note kar li hai — is saal hum sirf English ke liye volunteers arrange kar rahe hain. "
        "Jald hi doosre subjects bhi shuru honge. Kya aap English ke liye proceed karna chahenge?'\n"
        "Example (English): 'I've noted your request — this year we are focusing only on English. "
        "Other subjects will open up soon. Would you like to proceed with English?'\n\n"
        "Acknowledge what the coordinator has already shared before asking the next question."
    ),
    "pending_approval": (
        "STAGE: Review & Confirmation\n"
        "You MUST format your response EXACTLY as shown below — no paragraphs, no prose, no extra sentences.\n"
        "Use this exact structure:\n\n"
        "Here's what I've noted:\n"
        "• School: {school}\n"
        "• Subject(s): {subjects}\n"
        "• Grade(s): {grades}\n"
        "• Students: {count}\n"
        "• Days: {schedule}\n"
        "• Time: {time_slots}\n"
        "• Starting: {start_date}\n\n"
        "Kya sab theek hai? Confirm karein toh hum aage badhte hain.\n\n"
        "Fill in the actual values from CAPTURED SO FAR. "
        "Do NOT write a paragraph. Do NOT add any explanation before or after the bullets. "
        "The bullet list + one confirmation line is the ENTIRE response."
    ),
    "submitted": (
        "The need has been successfully registered. "
        "Thank the coordinator warmly. "
        "Let them know the team will start matching volunteers and will be in touch. "
        "Do NOT mention any reference ID or reference number."
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
        "Something needs human attention. Explain that someone from the Project Serve team "
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

    # ── Tool definitions (class-level so they're accessible as llm_adapter.COORDINATOR_TOOLS) ──

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
                "to check whether this is a renewal of existing support. "
                "IMPORTANT: school_id must be the UUID `id` field from the get_schools_for_coordinator "
                "or search_school result (e.g. '856475ed-f6b6-4bd7-b93d-cc0519c8d5a3'). "
                "NEVER use the UDISE code or any number extracted from the school name string."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "school_id": {
                        "type": "string",
                        "description": "UUID `id` field from the tool result — NOT the UDISE code from the school name",
                    },
                },
                "required": ["school_id"],
            },
        },
        {
            "name": "link_coordinator_to_school",
            "description": (
                "Link this coordinator to an existing school in Serve Need Service. "
                "Call this when coordinator confirmed they belong to a school found by search. "
                "IMPORTANT: school_id must be the UUID `id` field from the get_schools_for_coordinator "
                "or search_school result. NEVER use the UDISE code from the school name string."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "coordinator_id": {"type": "string"},
                    "school_id": {
                        "type": "string",
                        "description": "UUID `id` field from the tool result — NOT the UDISE code",
                    },
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

    # Combined tools for coordinator+school resolution in a single loop
    COMBINED_RESOLUTION_TOOLS: List[Dict] = []  # populated after class body

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
        stage: str = "coordinator",
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
                # Claude produced a text response — that is the message for the coordinator.
                # On the FIRST iteration with no prior tool results, this means Claude
                # skipped all lookups and is likely hallucinating. Force it to use tools.
                if iteration == 0 and not collected:
                    logger.warning(f"Claude skipped tool calls on first iteration (stage={stage}) — forcing tool use")
                    nudge = (
                        "You must call get_schools_for_coordinator with the coordinator's ID "
                        "before responding. Do not ask the coordinator which school they belong to "
                        "until you have checked the system first."
                        if stage == "school"
                        else
                        "Please use the available tools to look up the coordinator's details "
                        "before responding. If you already have a coordinator_id, call "
                        "get_schools_for_coordinator immediately. Do not assume or infer anything "
                        "without a tool result."
                    )
                    messages.append({"role": "assistant", "content": [
                        b for b in response.content if hasattr(b, "text")
                    ] or [{"type": "text", "text": "Let me check our records."}]})
                    messages.append({"role": "user", "content": nudge})
                    continue

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
        school_ctx: Optional[Dict[str, Any]] = None,
    ) -> str:
        """System prompt for RESOLVING_COORDINATOR tool-calling loop.

        When school_ctx is provided, the prompt also instructs Claude to proceed
        with school lookup immediately after coordinator identity is confirmed —
        all in the same tool-calling loop turn.
        """
        school_ctx = school_ctx or {}

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
        if school_ctx.get("school_id"):
            ctx_lines.append(f"- School already resolved: ID={school_ctx['school_id']}, name={school_ctx.get('school_name')}")
        if school_ctx.get("linked_schools_checked"):
            ctx_lines.append("- Linked schools already fetched (see previous tool results)")

        ctx_block = "\n".join(ctx_lines) if ctx_lines else "  (none yet)"

        # School lookup section — only shown when school tools are available
        school_section = ""
        if not school_ctx.get("school_id"):
            school_section = """
PHASE 2 — School Resolution (run immediately after coordinator is confirmed):
After you have a confirmed coordinator_id from a successful lookup, WITHOUT asking the coordinator anything:
A. Call get_schools_for_coordinator with that coordinator_id.
B. If it returns one school: confirm the school name naturally and call fetch_previous_needs with that school's `id` UUID.
C. If it returns status='multiple': list the school names from the `schools` array and ask the coordinator to pick one.
D. If it returns no schools (empty or status='not_found'): ask the coordinator for their school's UDISE code or name.
   - If they provide a UDISE code or name, call search_school.
   - If search_school returns one match: confirm that school name and call link_coordinator_to_school + fetch_previous_needs.
   - If search_school returns multiple: list them and ask the coordinator to confirm.
   - If search_school returns nothing: confirm it's a new school and gather name/district/state to call create_new_school.

UUID RULE — CRITICAL:
- Every school has an `id` field which is a UUID (e.g. "856475ed-f6b6-4bd7-b93d-cc0519c8d5a3").
- School names often contain a UDISE code as a suffix (e.g. "JHS NATKUR - 09270706702"). That number is NOT the school ID.
- When calling fetch_previous_needs or link_coordinator_to_school, ALWAYS use the `id` UUID from the tool result.
- NEVER extract a number from the school name string and use it as school_id.
"""

        return f"""{_EVID_CONTEXT}

GROUNDING RULES — NON-NEGOTIABLE:
- You are connected ONLY to the Project Serve Serve database through the provided tools.
- You have NO internet access, NO external registry, NO general knowledge about people or schools.
- NEVER use your training knowledge to identify a coordinator or school.
- The ONLY valid source of coordinator names, IDs, and school data is the text inside tool call results.
- CRITICAL: Do NOT generate responses like "I can see you're associated with a school" unless a tool has ALREADY returned that result this turn.
- If a tool returns status='error' OR serve_system_available=False, the lookup FAILED.
  Respond EXACTLY: "I'm having trouble accessing our records right now. Could you share your email address instead?"
  NEVER invent or guess identity from a failed tool call.
- If a tool returns status='not_found' or status='unlinked', the coordinator is genuinely not found.
  Do NOT infer who they are — ask for another identifier.

CURRENT STAGE: Coordinator Identity + School Resolution

What you know so far:
{ctx_block}

PHASE 1 — Coordinator Identity:
1. If coordinator is already resolved (coordinator_id known), skip identity lookups and go to Phase 2.
2. If phone is available and NOT yet tried, call lookup_coordinator_by_phone.
3. If phone lookup returned 'linked' AND the result contains a real coordinator ID, confirm their name warmly — do NOT ask for email — then immediately proceed to Phase 2.
4. If phone lookup returned 'unlinked' OR 'not_found', ask warmly: "Hmm, is number se koi record nahi mila. Kya aapne pehle kisi aur number se register kiya tha, ya aap Project Serve mein naye hain?" (or in English: "I couldn't find this number. Did you register with a different number, or are you new to Project Serve?"). Wait for their response before asking for email.
5. If email is available and NOT yet tried, call lookup_coordinator_by_email.
6. If email lookup returned 'linked' AND the result contains a real coordinator ID, confirm their name warmly, then proceed to Phase 2.
7. If email lookup returned 'unlinked' AND coordinator has confirmed they are new, ask for their name then call register_new_coordinator, then proceed to Phase 2.
8. If a tool returned an error or system was unavailable, apologise briefly and ask for an alternative identifier.
{school_section}
Conversational rules:
- Do not repeat lookups already tried.
- Do not mention "system", "database", "lookup", "entity", "osid", or any technical term to the coordinator.
- After a successful coordinator lookup, confirm naturally in their language: "Aap [Name] hain na? Great!" (or "I see you're [Name] — great!") then immediately call get_schools_for_coordinator without asking the coordinator anything.
- If school is already resolved, skip Phase 2 and respond with the school context.
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

GROUNDING RULES — NON-NEGOTIABLE:
- You are connected ONLY to the Project Serve Serve database through the provided tools.
- You have NO internet access, NO UDISE registry, NO external database, NO general knowledge about schools.
- NEVER use your training knowledge to identify a school from a UDISE code or school name.
  A UDISE code that you "recognise" from training is completely irrelevant — the code must be searched via tools.
- The ONLY valid source of school names, locations, and IDs is the text inside tool call results.
- CRITICAL: Do NOT generate responses like "I can see JHS Natkur in our system" or confirm a school name
  unless a tool has ALREADY returned that exact school name in its result this turn.
  Any school name you produce without a tool result is a hallucination and is strictly forbidden.
- If search_school returns a school name — that school name is what you use. Nothing else.
- If a tool returns status='error' OR serve_system_available=False, the lookup FAILED.
  Respond EXACTLY: "I wasn't able to find that in our system right now. Could you double-check the UDISE code or try the school name?"
  NEVER infer or fill in a school name from a failed or missing tool result.
- If search_school returns status='not_found' or an empty list, the school is not in our system yet.
  Confirm with the coordinator that it's a new school and gather details to create it.

UUID RULE — CRITICAL:
- Every school in the tool results has an `id` field which is a UUID (e.g. "856475ed-f6b6-4bd7-b93d-cc0519c8d5a3").
- School names often contain a UDISE code as a suffix (e.g. "JHS NATKUR - 09270706702"). That number is NOT the school ID.
- When calling fetch_previous_needs or link_coordinator_to_school, you MUST use the `id` field (UUID) from the tool result.
- NEVER extract a number from the school name string and use it as school_id. That will always fail.
- Example: for school {{"name": "JHS NATKUR - 09270706702", "id": "856475ed-f6b6-4bd7-b93d-cc0519c8d5a3"}},
  the correct school_id is "856475ed-f6b6-4bd7-b93d-cc0519c8d5a3", NOT "09270706702".

CURRENT STAGE: School Context Resolution
Coordinator: {coord_name} (ID: {coord_id or 'not yet in registry'})

What you know so far:
{ctx_block}

Your task:
1. If school is already resolved (school_id known) AND previous needs fetched — respond with that context.
2. If coordinator_id is available and linked schools NOT yet checked, call get_schools_for_coordinator first.
3. If get_schools_for_coordinator returns one school, confirm it with the coordinator naturally and call fetch_previous_needs using that school's `id` UUID.
4. If get_schools_for_coordinator returns status='multiple', read the `schools` array from the result and list each school as "[name] ([district])" to the coordinator. Ask them to confirm which school this need is for. Once they confirm, call link_coordinator_to_school and fetch_previous_needs using the confirmed school's `id` UUID.
5. If no linked schools found (or coordinator is new), ask: "Aapke school ka UDISE code kya hai? (11 digit number hota hai)" — coordinators in UP know this immediately. If they say they don't know it, ask for the school name.
6. If search_school returns one match, confirm that exact school name from the result with the coordinator, then call link_coordinator_to_school + fetch_previous_needs using the school's `id` UUID.
7. If search_school returns multiple matches, list the school names from the result and ask the coordinator to confirm which one is theirs.
8. If search_school returns no match or status='not_found', confirm the school is new, gather name + district + state, call create_new_school.
9. Once school is resolved and previous needs are fetched (or school is new), present context to the coordinator:
   - Existing school with previous needs: "I can see [School Name from tool result] had support for [subjects] for Grades [X-Y]. Is this year's need similar, or are there changes?"
   - New school: move straight to need capture.

Conversational rules:
- Do not mention system IDs, UUIDs, "database", "UDISE registry", or any technical term to the coordinator.
- School name in conversation = the name returned by the tool, not one you infer.
- If previous needs exist in the tool result, always surface them to offer renewal.
"""

    # ── Plain text generation ─────────────────────────────────────────────────

    async def extract_student_count(self, user_message: str) -> Optional[int]:
        """
        Ask the LLM to extract total student count from a free-text message.
        Handles per-grade inputs like "grade 6 - 30 and grade 7 - 20" → 50.
        Returns None if no count can be determined.
        """
        client = self._get_client()
        if client is None:
            return None
        try:
            response = await client.messages.create(
                model=self._model,
                max_tokens=10,
                system=(
                    "Extract the total number of students from the message. "
                    "If per-grade counts are given (e.g. 'grade 6 - 30, grade 7 - 20'), add them up. "
                    "Reply with ONLY a single integer. If no count is present, reply with 0."
                ),
                messages=[{"role": "user", "content": user_message}],
            )
            raw = next((b.text.strip() for b in response.content if hasattr(b, "text") and b.text), "0")
            val = int(re.search(r'\d+', raw).group()) if re.search(r'\d+', raw) else 0
            return val if 1 <= val <= 2000 else None
        except Exception as exc:
            logger.warning(f"extract_student_count LLM call failed: {exc}")
            return None

    async def classify_post_submission_intent(self, user_message: str) -> str:
        """
        Classify what the coordinator wants after a need has been submitted.
        Returns one of: 'another_need' | 'done' | 'unclear'
        """
        client = self._get_client()
        if client is None:
            return "unclear"
        try:
            response = await client.messages.create(
                model=self._model,
                max_tokens=10,
                system=(
                    "You are classifying a school coordinator's intent after they just submitted a teaching need.\n"
                    "Reply with EXACTLY one of these three words — nothing else:\n"
                    "  another_need  — they want to raise a new/additional need (different subject, grade, or class)\n"
                    "  done          — they are finished and just acknowledging or saying goodbye\n"
                    "  unclear       — the message is ambiguous\n"
                    "Examples of another_need: 'ek aur need hai', 'maths bhi chahiye', 'one more', "
                    "'different class ke liye bhi', 'science ke liye bhi', 'aur ek subject hai'\n"
                    "Examples of done: 'thank you', 'ok', 'shukriya', 'theek hai', 'bye', 'great'"
                ),
                messages=[{"role": "user", "content": user_message}],
            )
            raw = next((b.text.strip().lower() for b in response.content if hasattr(b, "text") and b.text), "unclear")
            if "another_need" in raw:
                return "another_need"
            if "done" in raw:
                return "done"
            return "unclear"
        except Exception as exc:
            logger.warning(f"classify_post_submission_intent failed: {exc}")
            return "unclear"

    async def extract_need_fields(
        self,
        conversation_history: List[Dict],
        user_message: str,
        existing_draft: Dict,
        previous_needs: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        Ask the LLM to extract all need fields from the conversation so far.
        Handles renewal ("same as last year"), partial changes, any language/phrasing.
        Returns a dict with only the fields that are now known (never overwrites with None).
        """
        client = self._get_client()
        if client is None:
            return {}

        # Build previous need summary for context
        prev_block = ""
        if previous_needs:
            parts = []
            for p in previous_needs[:3]:
                name = p.get("name", "")
                subj = p.get("subjects") or []
                grades = p.get("grade_levels") or []
                days = p.get("days", "")
                freq = p.get("frequency", "")
                slots = p.get("time_slots") or []
                slot_str = ""
                if slots and isinstance(slots, list):
                    first = slots[0] if slots else {}
                    if isinstance(first, dict):
                        st = first.get("startTime", "")
                        et = first.get("endTime", "")
                        if st and et:
                            slot_str = f"{st}–{et}"
                desc = f"- Subjects: {subj}, Grades: {grades}, Days: {days} {freq}, Time: {slot_str}"
                parts.append(desc)
            prev_block = "PREVIOUS YEAR NEEDS:\n" + "\n".join(parts)

        # Build current draft summary
        draft_block = ""
        if existing_draft:
            captured = {k: v for k, v in existing_draft.items()
                        if v is not None and v != "" and not (isinstance(v, list) and len(v) == 0)
                        and k in ("subjects", "grade_levels", "student_count", "schedule_preference", "time_slots")}
            if captured:
                draft_block = f"ALREADY CAPTURED: {json.dumps(captured)}"

        # Build recent conversation
        convo = ""
        for msg in conversation_history[-8:]:
            role = "Coordinator" if msg.get("role") == "user" else "Agent"
            convo += f"{role}: {msg.get('content', '')}\n"
        convo += f"Coordinator: {user_message}"

        system = """You are a data extraction assistant for Project Serve, an education NGO in India.
Extract need fields from the conversation between a school coordinator and the agent.

FIELDS TO EXTRACT:
- subjects: list of subjects (e.g. ["english", "mathematics", "science", "hindi"])
- grade_levels: list of grade numbers as strings (e.g. ["6", "7"])
- student_count: integer total (if per-grade given like "grade 6 - 30, grade 7 - 20", add them up = 50)
- schedule_preference: days of week as string (e.g. "Monday, Wednesday" or "Monday, Tuesday")
- time_slots: list of time slot strings (e.g. ["10:00-11:00"] or ["10:00-11:00 AM"])

RENEWAL RULE:
If previous year needs are shown and the coordinator says anything meaning "same" (yes, haan, same, theek hai, wahi chahiye, copy karo, bilkul, correct, ok, etc.) — copy ALL fields from previous needs.
If they say "same but change X" — copy all fields and apply the change.

IMPORTANT:
- Return ONLY fields you are confident about. Omit fields you don't know.
- Do NOT invent data. Only extract what the coordinator explicitly said or confirmed from previous needs.
- Return valid JSON only. No explanation, no markdown.
- For subjects, use lowercase canonical names: english, mathematics, science, hindi, social_studies, computer_basics
- grade_levels must be strings: ["6", "7"] not [6, 7]
- student_count must be an integer

Example output:
{"subjects": ["english"], "grade_levels": ["6", "7"], "student_count": 50, "schedule_preference": "Monday, Wednesday", "time_slots": ["10:00-11:00"]}

If nothing can be extracted, return: {}"""

        user_content = f"{prev_block}\n\n{draft_block}\n\nCONVERSATION:\n{convo}".strip()

        try:
            response = await client.messages.create(
                model=self._model,
                max_tokens=256,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = next((b.text.strip() for b in response.content if hasattr(b, "text") and b.text), "{}")
            # Strip markdown code fences if present
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
            result = json.loads(raw)
            logger.info(f"[extract_need_fields] extracted: {result}")
            return result if isinstance(result, dict) else {}
        except Exception as exc:
            logger.warning(f"extract_need_fields failed: {exc}")
            return {}

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
        grade_nudge: Optional[str] = None,
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
            grade_nudge=grade_nudge,
        )

        # Build conversation context (last 6 messages)
        convo = ""
        for msg in messages[-6:]:
            role = "Coordinator" if msg.get("role") == "user" else "Project Serve"
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
        grade_nudge: Optional[str] = None,
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
                name_str = p.get("name", "")
                subjects = p.get("subjects") or []
                if isinstance(subjects, str):
                    subjects = [subjects]
                desc = ", ".join(subjects) if subjects else name_str

                grade = p.get("grade_levels") or []
                if isinstance(grade, list):
                    grade = ", ".join(str(g) for g in grade)

                days = p.get("days") or p.get("schedule_preference") or ""
                freq = p.get("frequency") or ""

                slots = p.get("time_slots") or []
                slot_str = ""
                if slots and isinstance(slots, list):
                    first = slots[0] if slots else {}
                    if isinstance(first, dict):
                        st = first.get("startTime", "")
                        et = first.get("endTime", "")
                        if st and et:
                            slot_str = f"{st}–{et}"

                detail_parts = []
                if grade:
                    detail_parts.append(f"Grade {grade}")
                if days:
                    detail_parts.append(f"{days} ({freq})" if freq else days)
                if slot_str:
                    detail_parts.append(slot_str)
                full_desc = desc + (f" ({', '.join(detail_parts)})" if detail_parts else "")
                if full_desc:
                    prev_desc.append(full_desc)
            if prev_desc:
                prompt += f"\n\nPREVIOUS NEEDS: {'; '.join(prev_desc)}"
                prompt += (
                    "\n\nRENEWAL INSTRUCTION: Previous need details including subject, grade, days, and timings are shown above. "
                    "Present this to the coordinator naturally. Example: "
                    "'Pichhle saal aapke school mein English Grade 6 ka support tha — Monday, Tuesday 10:00–11:00. "
                    "Kya is saal bhi same chahiye?' "
                    "If they confirm same/yes/haan, treat subject, grade, days, timings, and end date as confirmed — "
                    "then ask ONLY for student count and start date, one at a time."
                )

        if need_draft:
            captured = []
            for key, label in [
                ("subjects", "Subjects"),
                ("grade_levels", "Grades"),
                ("student_count", "Students"),
                ("schedule_preference", "Days/schedule"),
                ("time_slots", "Time"),
            ]:
                val = need_draft.get(key)
                if val:
                    display = ", ".join(str(v) for v in val) if isinstance(val, list) else str(val)
                    captured.append(f"{label}: {display}")
            if captured:
                prompt += "\n\nCAPTURED SO FAR:\n" + "\n".join(captured)
                if stage != "pending_approval":
                    prompt += (
                        "\n\nIMPORTANT: Do NOT repeat or summarise the captured fields above in your reply. "
                        "The coordinator already told you these — just acknowledge briefly if relevant, "
                        "then ask only about the next missing thing."
                    )

        if missing_fields:
            field_labels = {
                "subjects": "what subjects students need help with",
                "grade_levels": "which grade levels",
                "student_count": "how many students in total (if they give per-grade counts like 'Grade 6 - 30, Grade 7 - 40', add them up and use the total)",
                "schedule_preference": "which days of the week (e.g. Monday & Wednesday, weekdays, twice a week)",
                "time_slots": "the class timing — what time of day the classes should happen (e.g. 10:00 AM to 11:00 AM). Ask: 'Kaunse time pe classes honi chahiye?' NOT 'kab se shuru karna hai' — do NOT ask about start date",
                "duration_weeks": "how many weeks of support",
            }
            next_field = field_labels.get(missing_fields[0], missing_fields[0])
            prompt += f"\n\nNEXT QUESTION: Ask only about {next_field}. One question, nothing else."

        if grade_nudge:
            prompt += f"\n\n{grade_nudge}"

        return prompt

    def _get_fallback_response(self, stage: str, missing_fields: Optional[List[str]] = None) -> str:
        fallbacks = {
            "initiated": "Hello! Welcome to Project Serve. I'm here to help you register teaching support for your school. Could you share your phone number to get started?",
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
                "duration_weeks": "For how many weeks would you like the support?",
            }
            base = field_prompts.get(missing_fields[0], base)
        return base


# Singleton
llm_adapter = NeedLLMAdapter()

# Populate combined tools list after class is fully defined
NeedLLMAdapter.COMBINED_RESOLUTION_TOOLS = NeedLLMAdapter.COORDINATOR_TOOLS + NeedLLMAdapter.SCHOOL_TOOLS

