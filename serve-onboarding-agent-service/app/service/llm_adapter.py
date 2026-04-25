"""
SERVE Onboarding Agent Service - LLM Adapter

Cost-effective approach: uses Haiku via direct httpx calls.
Each turn gets a fresh system prompt with only the current stage context.
Only the last 2 messages of history are sent to keep input tokens minimal.
No tool calling — the LLM only generates conversational responses.
"""
import json
import os
import logging
from typing import List, Dict, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_API_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-4-5-20251001")
_API_URL = "https://api.anthropic.com/v1/messages"
_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "15"))

# Video URLs — served from the onboarding agent's /media endpoint
_MEDIA_BASE_URL = os.environ.get("ONBOARDING_MEDIA_BASE_URL", "http://localhost:8002/media")
ONBOARDING_WELCOME_VIDEO_URL = f"{_MEDIA_BASE_URL}/welcome.mp4"
ONBOARDING_CLASSROOM_VIDEO_URL = f"{_MEDIA_BASE_URL}/serve_class_intro.mp4"
ONBOARDING_VIDEO_URL = os.environ.get("ONBOARDING_VIDEO_URL", "").strip()

# ── Base context (included in every system prompt) ──────────────────────────────

_BASE_CONTEXT = """You are an onboarding assistant for eVidyaloka, helping new volunteers join our mission to bring quality education to children in rural India through Project Serve in Uttar Pradesh.

Rules you MUST follow:
- Keep responses to 2-3 sentences maximum. Be warm but concise.
- Ask only ONE thing per response. Never combine multiple questions.
- Do not use markdown formatting — no bold, no headers, no bullet points, no asterisks.
- Do not use emojis excessively. One emoji per message at most.
- Never mention technical terms: workflow, orchestrator, MCP, agent, system, database.
- Do not say the volunteer is ineligible, rejected, or disqualified.
- Do not promise registration unless the stage is onboarding_complete.
- CRITICAL: Only ask about what is specified in the CURRENT STAGE instructions below. Do not ask about anything else — no city, no subjects, no availability, no motivation, no teaching experience. Stick strictly to the current stage."""


# ── Stage-specific prompts ──────────────────────────────────────────────────────

def _build_stage_prompt(
    stage: str,
    missing_fields: List[str],
    confirmed_fields: Dict,
) -> str:
    """Build the complete system prompt for a single turn."""

    if stage == "welcome":
        consent_given = confirmed_fields.get("consent_given") or False
        welcome_shown = confirmed_fields.get("welcome_shown") or False

        if not welcome_shown or not consent_given:
            # Turn 1: Welcome + steps + "shall we begin?"
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Welcome

Your task: Give a warm welcome. Introduce eVidyaloka and Project Serve in Uttar Pradesh in 2-3 sentences:
- eVidyaloka connects volunteers with children in rural India for online teaching.
- Project Serve brings quality English education to government school students in grades 6-8 in UP.
- Volunteers teach online for just 2-3 hours a week.

Then show the journey steps EXACTLY like this (plain text, include the emojis):

Here is what we will do together:
1. Orientation & Registration
2. Getting to Know You
3. Schedule Preferences
4. Teaching Assignment

End with: "Shall we begin?" or "Ready to get started?"

Do NOT ask why they are here yet. Do NOT share videos. Do NOT ask for name or email. Just welcome, show the 4 steps, and ask if they are ready to begin."""
        else:
            # Turn 2: Consent given → ask intent
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Welcome — Intent

The volunteer has agreed to begin.

Your task: Ask what brings them to eVidyaloka. Say something like: "What brings you to eVidyaloka?" or "What made you interested in volunteering with us?"

Keep it to 1 sentence. Do NOT share videos. Do NOT ask for name or email."""

    if stage == "orientation_video":
        welcome_response = confirmed_fields.get("welcome_response") or ""
        classroom_vid = ONBOARDING_CLASSROOM_VIDEO_URL

        if classroom_vid:
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Orientation

The volunteer said: "{welcome_response}"

Your task: Write a brief warm message (1-2 sentences) introducing the video below — it shows a glimpse of an actual online class with eVidyaloka. Then include the video tag EXACTLY as shown. End by asking the volunteer to reply "done" or "ready" when they have watched.

[VIDEO:{classroom_vid}|A glimpse of an actual eVidyaloka online class]

IMPORTANT: Include the [VIDEO:...] tag exactly as it appears above in your response. The system will render it as an embedded video. Do not convert it to a link or remove it."""
        else:
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Orientation

The volunteer said: "{welcome_response}"

Your task: Briefly explain how eVidyaloka works — volunteers teach online for 2-3 hours a week, connecting with rural school students via video call. Then ask if they are ready to continue.
Do NOT ask eligibility or profile questions."""

    if stage == "eligibility_screening":
        # Check for pending clarifications
        pending_clarifications = [f for f in missing_fields if f.endswith("_clarification")]
        if pending_clarifications:
            field = pending_clarifications[0].replace("_clarification", "")
            clarifications = {
                "age_18_plus": "Their previous answer about age was unclear. Ask gently: 'Just to confirm, are you 18 years or older?'",
                "has_internet_and_device": "They seemed unsure about device/internet. Clarify: 'A smartphone with mobile data works too. Do you have any device with internet access?'",
                "accepts_unpaid_role": "They seemed unsure about the unpaid role. Clarify warmly: 'Just to be clear, this is a volunteer role. Are you comfortable with that?'",
            }
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Eligibility — Clarification

{clarifications.get(field, "Ask the volunteer to clarify their previous answer.")}

Be warm and non-judgmental. Do not make them feel they gave a wrong answer.
Your ENTIRE response must be about this one clarification. Nothing else."""

        # Determine which question to ask
        elig = confirmed_fields
        if elig.get("age_18_plus") is not True:
            question = "Are you 18 years of age or older?"
        elif elig.get("has_internet_and_device") is not True:
            question = "Do you have a device like a laptop, tablet, or smartphone with internet access for online classes?"
        elif elig.get("accepts_unpaid_role") is not True:
            question = "This is a volunteer, unpaid role. Are you comfortable with that?"
        else:
            question = "All eligibility checks are done. Acknowledge warmly and say you will now collect a few details."

        return f"""{_BASE_CONTEXT}

CURRENT STAGE: Eligibility Screening

Your task: Ask this ONE question and nothing else:
"{question}"

Add a brief warm lead-in (one sentence max), then ask the question.
Do NOT ask for name, email, qualification, or anything beyond this one question.
Your ENTIRE response must be about this eligibility question."""

    if stage == "contact_capture":
        name = confirmed_fields.get("full_name")
        email = confirmed_fields.get("email")
        phone = confirmed_fields.get("phone")
        qualification = confirmed_fields.get("qualification")

        if not name:
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Contact Details — Name

Your task: Ask for the volunteer's full name. Nothing else.
Example: "Could you share your full name?"
Do NOT ask for email, phone, qualification, or anything else."""

        if not email:
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Contact Details — Email

We know: Name = {name}

Your task: Thank them briefly, then ask for their email address. Nothing else.
Do NOT ask for phone, qualification, or anything else."""

        if not phone:
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Contact Details — Phone

We know: Name = {name}, Email = {email}

Your task: Ask for their phone number so the team can reach them. Nothing else.
Example: "Could you share your phone number?"
Do NOT ask for qualification or anything else."""

        if not qualification:
            return f"""{_BASE_CONTEXT}

CURRENT STAGE: Contact Details — Qualification

We know: Name = {name}, Email = {email}, Phone = {phone}

Your task: Ask about their educational qualification. Nothing else.
Example: "What is your educational qualification?"
Accept any answer — degree name, "graduate", "12th pass", etc."""

        return f"""{_BASE_CONTEXT}

CURRENT STAGE: Contact Details — Complete

All details captured. Thank them briefly and say you will now show a quick summary for confirmation."""

    if stage == "registration_review":
        name = confirmed_fields.get("full_name", "")
        email = confirmed_fields.get("email", "")
        phone = confirmed_fields.get("phone", "")
        qualification = confirmed_fields.get("qualification", "")

        summary_parts = []
        if name: summary_parts.append(f"Name: {name}")
        if email: summary_parts.append(f"Email: {email}")
        if phone: summary_parts.append(f"Phone: {phone}")
        if qualification: summary_parts.append(f"Qualification: {qualification}")
        summary = "\n".join(summary_parts)
        return f"""{_BASE_CONTEXT}

CURRENT STAGE: Registration Review

Volunteer details:
{summary}

Your task: Present these details warmly and ask if everything looks correct.
Say something like: "Here is what I have..." then list the details, then ask "Does this look correct? If you want to change anything, let me know."
Your ENTIRE response is the summary + confirmation question. Nothing else."""

    if stage == "onboarding_complete":
        name = confirmed_fields.get("full_name", "")
        return f"""{_BASE_CONTEXT}

CURRENT STAGE: Registration Complete

Your task: Thank {name} briefly for completing registration. Keep it to ONE short sentence like "Your registration is complete, {name}!" Do not mention next steps, matching, schools, or getting to know them. Just a brief celebration."""

    if stage == "human_review":
        return f"""{_BASE_CONTEXT}

CURRENT STAGE: Review Pending

Your task: Say warmly that the team will review the details and get back shortly. Do not say they are ineligible or rejected. Keep it to 2 sentences."""

    if stage == "paused":
        return f"""{_BASE_CONTEXT}

CURRENT STAGE: Paused

Your task: Be understanding. Let them know they can return anytime and their progress is saved. Keep it to 2 sentences."""

    # Fallback
    return f"""{_BASE_CONTEXT}

Your task: Stay in the current step. Do not ask additional questions. If the volunteer said something unexpected, acknowledge briefly and redirect."""


# ── LLM call ────────────────────────────────────────────────────────────────────

async def _call_llm(system_prompt: str, messages: List[Dict[str, str]]) -> str:
    """
    Make a single Anthropic API call via httpx.
    Sends only the system prompt + provided messages. No accumulated state.
    """
    if not _API_KEY:
        logger.warning("No EMERGENT_LLM_KEY — using fallback response")
        return "Welcome to eVidyaloka! We are glad you are interested in volunteering."

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                _API_URL,
                headers={
                    "x-api-key": _API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": _MODEL,
                    "max_tokens": 300,
                    "system": system_prompt,
                    "messages": messages,
                },
            )
            response.raise_for_status()

        body = response.json()
        text = body.get("content", [{}])[0].get("text", "").strip()
        return text or "How can I help you today?"

    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return "Welcome to eVidyaloka! We are glad you are interested in volunteering."


# ── Main adapter class ──────────────────────────────────────────────────────────

class LLMAdapter:
    """
    Onboarding LLM adapter — cost-effective, stage-focused.
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

        # Build fresh system prompt for this stage
        system_prompt = _build_stage_prompt(
            stage=stage,
            missing_fields=missing_fields,
            confirmed_fields=confirmed_fields,
        )

        # Build minimal message history — only last 2 messages + current user message
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
