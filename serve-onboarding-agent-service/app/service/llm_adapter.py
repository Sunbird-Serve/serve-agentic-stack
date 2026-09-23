"""
SERVE Onboarding Agent Service - LLM Adapter (v2)

Improvements:
- Welcome collapsed to 1 turn (intro + ask intent together)
- Video non-blocking (shown with eligibility transition)
- Bundled eligibility (all 3 checks in one question)
- Reluctance handling (why do you need my info?)
- Email typo detection prompts
- Motivation personalization in subsequent stages
- Progress hints to reduce drop-off
- Transparent eligibility failure messaging
"""
import asyncio
import os
import logging
from typing import List, Dict, Optional

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_PROVIDER_KEY_VARS = (
    "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
    "OPENAI_API_KEY", "GEMINI_API_KEY", "EMERGENT_LLM_KEY",
)
_API_KEY = next((os.environ[k] for k in _PROVIDER_KEY_VARS if os.environ.get(k)), "")
if os.environ.get("EMERGENT_LLM_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = os.environ["EMERGENT_LLM_KEY"]
_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-4-5-20251001")
_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "25"))
_MAX_ATTEMPTS = int(os.environ.get("LLM_MAX_ATTEMPTS", "2"))
_RETRY_BACKOFF_SECONDS = float(os.environ.get("LLM_RETRY_BACKOFF_SECONDS", "1"))

_UNAVAILABLE_RESPONSE = (
    "I'm having a little trouble responding right now. Could you please send that again?"
)

# Video URLs
_MEDIA_BASE_URL = os.environ.get("ONBOARDING_MEDIA_BASE_URL", "http://localhost:8002/media")
ONBOARDING_CLASSROOM_VIDEO_URL = f"{_MEDIA_BASE_URL}/serve_class_intro.mp4"

# ── Base context (included in every system prompt) ──────────────────────────────

_BASE_CONTEXT = """You are an onboarding assistant for eVidyaloka, helping new volunteers join Project Serve — bringing quality English education to government school students in grades 6-8 in Uttar Pradesh. Volunteers teach online for 2-3 hours a week.

Rules you MUST follow:
- Keep responses to 2-3 sentences maximum. Be warm but concise.
- Ask only ONE thing per response unless the stage says otherwise.
- Do not use markdown formatting — no bold, no headers, no bullet points, no asterisks.
- Do not use emojis excessively. One emoji per message at most.
- Never mention technical terms: workflow, orchestrator, MCP, agent, system, database, session.
- Do not say the volunteer is ineligible, rejected, or disqualified.
- Do not promise registration unless the stage is onboarding_complete.
- CRITICAL: Only respond with what the CURRENT STAGE instructions specify. Nothing else.
- IMPORTANT: Volunteers MUST use a laptop, computer, or tablet with internet for online teaching. Mobile phones are NOT sufficient. If asked about mobile/phone teaching, clearly say a laptop, computer, or tablet is required.
- IMPORTANT: The minimum teaching commitment is 2 days per week (2-3 hours total). If asked, clarify this. One day per week is not enough."""


# ── Stage-specific prompts ──────────────────────────────────────────────────────

def _build_stage_prompt(
    stage: str,
    missing_fields: List[str],
    confirmed_fields: Dict,
) -> str:
    """Build the complete system prompt for a single turn."""

    welcome_response = confirmed_fields.get("welcome_response") or ""
    motivation_context = ""
    if welcome_response:
        motivation_context = f'\nThe volunteer said their motivation is: "{welcome_response[:200]}". Reference this naturally if relevant.'

    # ── WELCOME (v2: single turn — intro + ask intent) ──────────────────────
    if stage == "welcome":
        return f"""{_BASE_CONTEXT}

CURRENT STAGE: Welcome (Step 1/4 — Orientation & Registration)

Your task: Give a warm, brief welcome in 2-3 sentences. Mention that eVidyaloka connects volunteers with rural school children for online teaching through Project Serve in UP (2-3 hours/week). Then ask what brings them here.

Combine the welcome and the question in ONE message. Example:
"Welcome to eVidyaloka! We connect volunteers with children in rural India for online English classes — just 2-3 hours a week can make a real difference. What brings you here today?"

Do NOT show journey steps. Do NOT share videos. Do NOT ask for name or details yet."""

    # ── ORIENTATION VIDEO (v2: non-blocking — show video + transition message) ──
    if stage == "orientation_video":
        classroom_vid = ONBOARDING_CLASSROOM_VIDEO_URL

        if classroom_vid:
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Orientation Video (Step 1/4)
{motivation_context}

The volunteer just shared what brings them here. Your task:
1. Briefly acknowledge their motivation warmly (1 sentence referencing what they said).
2. Include the video tag EXACTLY: [VIDEO:{classroom_vid}|A glimpse of an eVidyaloka online class]
3. AFTER the video tag, on a new line say: "Watch this short clip to see how our classes work. Let me know when you're ready to move on!"

IMPORTANT: Include the [VIDEO:...] tag exactly as shown. The system renders it as a video.
The video tag MUST come BEFORE the "ready to continue" message.
Do NOT ask eligibility or contact details here. Just show the video and wait."""
        else:
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Orientation (Step 1/4)
{motivation_context}

Briefly acknowledge their motivation (1 sentence), then explain how eVidyaloka works — volunteers teach online for 2-3 hours a week via video call. Ask if they are ready to continue."""

    # ── ELIGIBILITY (always bundled — video was already shown) ─────────────────
    if stage == "eligibility_screening":
        eligibility = confirmed_fields

        # Check for pending clarifications (negative answer needs re-confirm)
        pending_clarifications = [f for f in missing_fields if f.endswith("_clarification")]
        if pending_clarifications:
            field = pending_clarifications[0].replace("_clarification", "")
            clarifications = {
                "age_18_plus": "Their previous answer about age was unclear. Ask gently: 'Just to confirm, are you 18 years or older?'",
                "has_internet_and_device": "They seemed unsure about device/internet. Clarify warmly: 'Do you have a laptop or computer with internet access for online classes?'",
                "accepts_unpaid_role": "They seemed unsure about the volunteer nature. Clarify: 'This is a volunteer role — no payment, but a chance to make real impact. Are you comfortable with that?'",
            }
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Eligibility — Clarification (Step 1/4)
{motivation_context}

{clarifications.get(field, "Ask the volunteer to clarify their previous answer.")}

Be warm and non-judgmental. Your ENTIRE response is about this one clarification."""

        # Bundled question (all 3 checks in one)
        all_unanswered = all(eligibility.get(f) is None for f in ["age_18_plus", "has_internet_and_device", "accepts_unpaid_role"])
        if all_unanswered:
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Eligibility — Quick Check (Step 1/4)
{motivation_context}

Your task: Ask all three eligibility checks as bullet points in ONE message:

"Before we proceed, I just need to confirm a few things:
• Are you 18 years or older?
• Do you have a laptop/computer with internet access?
• Are you comfortable that this is a voluntary, unpaid role?

A simple 'yes' to all works!"

Keep it brief and warm. Use bullet points exactly as shown. Do NOT ask for name, email, or phone. Do NOT mention smartphones.
Your ENTIRE response is this one bundled question."""

        # Individual fallback (if bundled "no" was given or partial)
        if eligibility.get("age_18_plus") is not True:
            question = "Are you 18 years of age or older?"
        elif eligibility.get("has_internet_and_device") is not True:
            question = "Do you have a laptop or computer with internet access for online classes?"
        elif eligibility.get("accepts_unpaid_role") is not True:
            question = "This is a volunteer, unpaid role — are you comfortable with that?"
        else:
            question = "All checks done!"
            # All eligibility passed — add consent confirmation before moving on
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Eligibility — Consent Confirmation (Step 1/4)
{motivation_context}

All eligibility checks have passed. Before we move on, get their explicit consent.

Your task: Say something like:
"Perfect! Just to formally confirm before we proceed — you are declaring that you are 18 years or older, you have internet and device access for online teaching, and you understand this is a voluntary, unpaid role. By continuing, you consent to these terms. Shall we go ahead?"

Keep it brief and warm but make sure all three points are mentioned explicitly. Wait for their confirmation before proceeding.
Do NOT ask about hours, availability, schedule, or anything else. ONLY the consent confirmation."""

        return f"""{_BASE_CONTEXT}

CURRENT STAGE: Eligibility — Individual Check (Step 1/4)
{motivation_context}

Your task: Ask this ONE question: "{question}"
Be warm, brief. Your ENTIRE response is about this one question."""

    # ── CONTACT CAPTURE (v3: name + email + phone together, no qualification) ───
    if stage == "contact_capture":
        name = confirmed_fields.get("full_name")
        email = confirmed_fields.get("email")
        phone = confirmed_fields.get("phone")
        is_reluctant = confirmed_fields.get("volunteer_reluctant", False)
        email_typo = confirmed_fields.get("email_typo_suggestion")

        # Email typo detected
        if email_typo:
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Contact Details — Email Typo Check (Step 1/4)

I noticed the email might have a typo. Ask: "Did you mean {email_typo}?"
Your ENTIRE response is about confirming the email."""

        # Reluctance handling
        if is_reluctant:
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Contact Details — Privacy Assurance (Step 1/4)
{motivation_context}

The volunteer is hesitant about sharing details. Reassure briefly:
- Info is only used to coordinate class schedules
- Stays private within the eVidyaloka team
Then gently re-ask. Keep to 2 sentences."""

        # All 3 missing → ask together
        remaining = []
        if not name:
            remaining.append("full name")
        if not email:
            remaining.append("email address")
        if not phone:
            remaining.append("phone number")

        if len(remaining) >= 2:
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Contact Details (Step 1/4)
{motivation_context}

Your task: Ask for ALL of these in one natural sentence: {', '.join(remaining)}.
Example: "Could you share your full name, email address, and phone number so I can get you registered?"

Ask all in ONE sentence. Keep it to 2 sentences total (brief lead-in + the ask).
Do NOT ask about qualification, availability, or anything else."""

        elif len(remaining) == 1:
            field = remaining[0]
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Contact Details — Last Field (Step 1/4)
{motivation_context}

Your task: Ask for their {field}. One sentence, brief and natural."""

        # All captured
        return f"""{_BASE_CONTEXT}

CURRENT STAGE: Contact Details — Complete (Step 1/4)

All details captured! Say something brief like "Got it, thanks!" and move to the summary."""

    # ── REGISTRATION REVIEW ─────────────────────────────────────────────────────
    if stage == "registration_review":
        name = confirmed_fields.get("full_name", "")
        email = confirmed_fields.get("email", "")
        phone = confirmed_fields.get("phone", "")

        # Build the EXACT text the LLM must say (no improvisation allowed)
        summary_lines = []
        if name:
            summary_lines.append(f"Name: {name}")
        if email:
            summary_lines.append(f"Email: {email}")
        if phone:
            summary_lines.append(f"Phone: {phone}")
        summary_text = "\n".join(summary_lines)

        return f"""{_BASE_CONTEXT}

CURRENT STAGE: Registration Review (Step 1/4)

Your task: Present the volunteer's details and ask for confirmation.

You MUST say EXACTLY this (do not change the values, do not add extra fields, do not make up data):

"Here is what I have:
{summary_text}

Does this look right? Let me know if you want to change anything."

Copy the above text EXACTLY. Do NOT modify the name, email, or phone values. Do NOT add qualification, age, or any other fields. Just present what is shown above and ask for confirmation."""

    # ── ONBOARDING COMPLETE ─────────────────────────────────────────────────────
    if stage == "onboarding_complete":
        name = confirmed_fields.get("full_name", "")
        email = confirmed_fields.get("email", "")
        import os
        portal_url = os.environ.get("SERVE_PORTAL_URL", "https://up.serve.net.in")
        default_password = os.environ.get("SERVE_DEFAULT_PASSWORD")
        password_line = (
            f"Password: {default_password} (you'll be asked to change this on first login)\n"
            if default_password else
            "Password: Please use the password setup instructions sent to your registered email or phone.\n"
        )

        return f"""{_BASE_CONTEXT}

CURRENT STAGE: Registration Complete (Step 1/4)

Your task: Congratulate {name} and share their login credentials. Say EXACTLY this:

"You're all set, {name}! Your SERVE account has been created.

Here are your login details:
Portal: {portal_url}
Username: {email}
{password_line}

You can now log into the SERVE Portal to track your teaching journey. Welcome aboard!"

Copy the above EXACTLY. Do NOT change the URL, username, or password instruction. Do NOT add extra information."""

    # ── HUMAN REVIEW (v2: transparent messaging) ────────────────────────────────
    if stage == "human_review":
        review_reason = confirmed_fields.get("review_reason", "")
        reason_messages = {
            "age_18_plus": "We require volunteers to be 18 or older for safeguarding reasons.",
            "has_internet_and_device": "Online teaching needs a device with internet access.",
            "accepts_unpaid_role": "We understand — volunteering is not for everyone right now.",
        }
        specific_msg = reason_messages.get(review_reason, "")

        return f"""{_BASE_CONTEXT}

CURRENT STAGE: Cannot Continue

{f'Context: {specific_msg}' if specific_msg else ''}

Your task: Be warm and honest. Do NOT say "the team will review" — be transparent:
- If the reason is age: "We need volunteers to be 18+ for child safety. If your situation changes, you are always welcome back!"
- If the reason is device/internet: "Online teaching needs internet access. If you get access in the future, we would love to have you!"
- If the reason is unpaid: "We totally understand. If you ever want to give it a try, we will be here!"
- Default: "Unfortunately we cannot proceed right now, but you are always welcome to try again in the future."

Keep it to 2 sentences. Be kind, not clinical."""

    # ── PAUSED ──────────────────────────────────────────────────────────────────
    if stage == "paused":
        return f"""{_BASE_CONTEXT}

CURRENT STAGE: Paused

Your task: Be understanding. Let them know their progress is saved and they can return anytime. Keep it to 2 sentences. Example: "No worries at all! Your progress is saved — just message anytime to pick up where you left off." """

    # ── Fallback ────────────────────────────────────────────────────────────────
    return f"""{_BASE_CONTEXT}

Your task: Stay in the current step. If the volunteer said something unexpected, acknowledge briefly and redirect to what you need from them."""


# ── LLM call ────────────────────────────────────────────────────────────────────

async def _call_llm(system_prompt: str, messages: List[Dict[str, str]]) -> str:
    """Make a single LLM call via LiteLLM with retry."""
    if not _API_KEY:
        logger.warning("No API key configured — using fallback response")
        return _UNAVAILABLE_RESPONSE

    import litellm
    litellm.drop_params = True

    llm_messages = [{"role": "system", "content": system_prompt}] + messages

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = await litellm.acompletion(
                model=_MODEL,
                messages=llm_messages,
                max_tokens=350,
                timeout=_TIMEOUT,
            )
            text = response.choices[0].message.content.strip()
            return text or "How can I help you today?"

        except Exception as e:
            is_last_attempt = attempt == _MAX_ATTEMPTS
            log = logger.error if is_last_attempt else logger.warning
            log(f"LLM call failed (attempt {attempt}/{_MAX_ATTEMPTS}): {e}")
            if not is_last_attempt:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)

    return _UNAVAILABLE_RESPONSE


def _render_registration_review(confirmed_fields: Dict) -> str:
    summary_lines = []
    name = confirmed_fields.get("full_name")
    email = confirmed_fields.get("email")
    phone = confirmed_fields.get("phone")

    if name:
        summary_lines.append(f"Name: {name}")
    if email:
        summary_lines.append(f"Email: {email}")
    if phone:
        summary_lines.append(f"Phone: {phone}")

    summary_text = "\n".join(summary_lines)
    return f"Here is what I have:\n{summary_text}\n\nDoes this look right? Let me know if you want to change anything."


def _render_onboarding_complete(confirmed_fields: Dict) -> str:
    name = confirmed_fields.get("full_name", "")
    email = confirmed_fields.get("email", "")
    portal_url = os.environ.get("SERVE_PORTAL_URL", "https://up.serve.net.in")
    default_password = os.environ.get("SERVE_DEFAULT_PASSWORD")
    password_line = (
        f"Password: {default_password} (you'll be asked to change this on first login)\n"
        if default_password else
        "Password: Please use the password setup instructions sent to your registered email or phone.\n"
    )

    return (
        f"You're all set, {name}! Your SERVE account has been created.\n\n"
        "Here are your login details:\n"
        f"Portal: {portal_url}\n"
        f"Username: {email}\n"
        f"{password_line}\n"
        "You can now log into the SERVE Portal to track your teaching journey. Welcome aboard!"
    )


def _render_human_review(confirmed_fields: Dict) -> str:
    review_reason = confirmed_fields.get("review_reason", "")
    if review_reason == "age_18_plus":
        return "We need volunteers to be 18+ for child safety. If your situation changes, you are always welcome back!"
    if review_reason == "has_internet_and_device":
        return "Online teaching needs a laptop or computer with internet access. If you get access in the future, we would love to have you!"
    if review_reason == "accepts_unpaid_role":
        return "We totally understand. If you ever want to give volunteering a try, we will be here!"
    return "Unfortunately we cannot proceed right now, but you are always welcome to try again in the future."


def _render_eligibility(missing_fields: List[str], confirmed_fields: Dict) -> str:
    pending_clarifications = [f for f in missing_fields if f.endswith("_clarification")]
    if pending_clarifications:
        field = pending_clarifications[0].replace("_clarification", "")
        if field == "age_18_plus":
            return "Just to confirm, are you 18 years or older?"
        if field == "has_internet_and_device":
            return "Do you have a laptop or computer with internet access for online classes?"
        if field == "accepts_unpaid_role":
            return "This is a volunteer role with no payment, but a chance to make real impact. Are you comfortable with that?"
        return "Could you please clarify your previous answer?"

    eligibility_fields = ["age_18_plus", "has_internet_and_device", "accepts_unpaid_role"]
    all_unanswered = all(confirmed_fields.get(f) is None for f in eligibility_fields)
    if all_unanswered:
        return (
            "Before we proceed, I just need to confirm a few things:\n"
            "• Are you 18 years or older?\n"
            "• Do you have a laptop/computer with internet access?\n"
            "• Are you comfortable that this is a voluntary, unpaid role?\n\n"
            "A simple 'yes' to all works!"
        )

    if confirmed_fields.get("age_18_plus") is not True:
        return "Are you 18 years of age or older?"
    if confirmed_fields.get("has_internet_and_device") is not True:
        return "Do you have a laptop or computer with internet access for online classes?"
    if confirmed_fields.get("accepts_unpaid_role") is not True:
        return "This is a volunteer, unpaid role. Are you comfortable with that?"
    return (
        "Perfect! Just to formally confirm before we proceed, you are declaring that you are 18 years or older, "
        "have internet and device access for online teaching, and understand this is a voluntary, unpaid role. Shall we go ahead?"
    )


def _render_contact_capture(confirmed_fields: Dict) -> str:
    email_typo = confirmed_fields.get("email_typo_suggestion")
    if email_typo:
        return f"I noticed the email might have a typo. Did you mean {email_typo}?"

    if confirmed_fields.get("volunteer_reluctant", False):
        return (
            "Your details are only used to coordinate class schedules and will stay private within the eVidyaloka team. "
            "Could you share the missing details so we can continue?"
        )

    remaining = []
    if not confirmed_fields.get("full_name"):
        remaining.append("full name")
    if not confirmed_fields.get("email"):
        remaining.append("email address")
    if not confirmed_fields.get("phone"):
        remaining.append("phone number")

    if len(remaining) >= 2:
        return f"Could you share your {', '.join(remaining)} so I can get you registered?"
    if len(remaining) == 1:
        return f"Could you share your {remaining[0]}?"
    return "Got it, thanks!"


def _render_deterministic_response(stage: str, missing_fields: List[str], confirmed_fields: Dict) -> Optional[str]:
    if stage == "eligibility_screening":
        return _render_eligibility(missing_fields, confirmed_fields)
    if stage == "contact_capture":
        return _render_contact_capture(confirmed_fields)
    if stage == "registration_review":
        return _render_registration_review(confirmed_fields)
    if stage == "onboarding_complete":
        return _render_onboarding_complete(confirmed_fields)
    if stage == "human_review":
        return _render_human_review(confirmed_fields)
    if stage == "paused":
        return "No worries at all! Your progress is saved, and you can message anytime to pick up where you left off."
    return None


# ── Main adapter class ──────────────────────────────────────────────────────────

class LLMAdapter:
    """
    Onboarding LLM adapter v2 — cost-effective, stage-focused.
    Each turn gets a fresh system prompt. Only last 2 messages of history sent.
    """

    async def generate_response(
        self,
        stage: str,
        messages: List[Dict[str, str]],
        user_message: str,
        missing_fields: List[str] = None,
        confirmed_fields: Dict = None,
        memory_context: str = None,
    ) -> str:
        missing_fields = missing_fields or []
        confirmed_fields = confirmed_fields or {}

        deterministic_response = _render_deterministic_response(
            stage=stage,
            missing_fields=missing_fields,
            confirmed_fields=confirmed_fields,
        )
        if deterministic_response is not None:
            return deterministic_response

        # Build fresh system prompt for this stage
        system_prompt = _build_stage_prompt(
            stage=stage,
            missing_fields=missing_fields,
            confirmed_fields=confirmed_fields,
        )

        # Build minimal message history — only last 2 messages + current
        api_messages = []
        if messages:
            recent = messages[-2:]
            for msg in recent:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("user", "assistant") and content:
                    api_messages.append({"role": role, "content": content})

        # Add current user message
        if user_message and user_message not in ("__handoff__", "__auto_continue__"):
            api_messages.append({"role": "user", "content": user_message})

        # Ensure messages alternate correctly (Anthropic requires user-first)
        if not api_messages or api_messages[0]["role"] != "user":
            api_messages.insert(0, {"role": "user", "content": user_message or "Hello"})

        # Deduplicate consecutive same-role messages
        cleaned = [api_messages[0]]
        for msg in api_messages[1:]:
            if msg["role"] != cleaned[-1]["role"]:
                cleaned.append(msg)
        api_messages = cleaned

        return await _call_llm(system_prompt, api_messages)


# Singleton
llm_adapter = LLMAdapter()
