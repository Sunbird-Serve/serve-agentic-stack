"""
SERVE Onboarding Agent Service - LLM Adapter Layer (Enhanced)
Configurable LLM integration with eVidyaloka-aligned prompting

Key improvements:
- Warm, volunteer-oriented tone aligned with eVidyaloka mission
- Simple language without technical jargon
- Mission-aligned but not preachy messaging
- Conversational and encouraging style
"""
import os
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from dotenv import load_dotenv
import logging

load_dotenv()
logger = logging.getLogger(__name__)

ONBOARDING_VIDEO_URL = os.environ.get("ONBOARDING_VIDEO_URL", "").strip()


# ============ eVidyaloka Context ============

EVIDYALOKA_CONTEXT = """
eVidyaloka's Mission:
eVidyaloka enables equitable access to quality education for children in rural India. 
We connect passionate volunteers with students who need support, creating meaningful 
educational experiences that transform lives.

Communication Style:
- Warm and welcoming - like greeting a new friend joining a cause
- Respectful and encouraging - acknowledge their interest in helping
- Simple, clear language - avoid jargon, be direct yet kind
- Mission-connected - help them feel part of something meaningful
- Never use technical terms like: workflow, orchestrator, MCP, agent, system

Key Values:
- Every child deserves quality education
- Volunteers are the heart of our mission
- Small efforts create big impact
- Learning is a two-way journey
"""


# ============ Dynamic Prompting ============

def build_system_prompt(
    stage: str,
    missing_fields: List[str],
    confirmed_fields: Dict,
    conversation_length: int = 0,
    memory_context: str = None
) -> str:
    """
    Build a contextual system prompt based on current state and data needs.
    
    This function creates prompts that:
    1. Maintain eVidyaloka's warm, mission-oriented tone
    2. Dynamically focus on collecting missing information
    3. Acknowledge what we already know about the volunteer
    4. Progress naturally through the conversation
    5. Incorporate memory context for returning volunteers
    """
    
    # Base context for all stages
    base_prompt = f"""You are an onboarding assistant for eVidyaloka, helping new volunteers join 
our mission to bring quality education to children in rural India.

{EVIDYALOKA_CONTEXT}

Guidelines:
- Keep responses concise (2-3 sentences max)
- Be warm but not overly effusive
- Ask one question at a time
- Never mention technical terms or internal processes
- Make the volunteer feel valued and welcomed
- Stay within the current onboarding step; do not jump ahead
- Do not say the volunteer is ineligible, rejected, or disqualified
- If the case needs internal review, say politely that the team will review and get back
- Do not promise successful registration unless the current stage is onboarding_complete
"""
    
    # Add memory context if available (for returning volunteers)
    if memory_context:
        base_prompt += f"""

MEMORY CONTEXT (use naturally, don't explicitly mention having memory):
{memory_context}
"""
    
    # Stage-specific behavior
    stage_instructions = _get_stage_instructions(stage, missing_fields, confirmed_fields)
    
    # Add field collection guidance if needed
    field_guidance = _get_field_collection_guidance(missing_fields, confirmed_fields)
    
    # Conversation context
    context_note = ""
    if conversation_length > 3:
        context_note = "\n\nNote: We've been chatting for a bit. Keep moving the conversation forward naturally."
    
    return f"{base_prompt}\n\n{stage_instructions}\n\n{field_guidance}{context_note}"


def _get_stage_instructions(stage: str, missing_fields: List[str], confirmed_fields: Dict) -> str:
    """Get stage-specific instructions."""
    
    if stage == "welcome":
        return """CURRENT STAGE: Welcome

Your task: Greet the volunteer warmly and briefly explain that you will first share a short orientation video before asking a few simple questions.
Do not ask for profile details yet.
"""
    
    elif stage == "orientation_video":
        video_note = (
            f"Share this video link exactly once: {ONBOARDING_VIDEO_URL}\n"
            if ONBOARDING_VIDEO_URL else
            "Mention that a short orientation video is being shared.\n"
        )
        return f"""CURRENT STAGE: Orientation Video

Your task: Begin with a warm welcome, then share the short orientation video and politely ask the volunteer to reply once they are ready to continue.
{video_note}
Keep the tone welcoming and simple. Do not ask eligibility or profile questions in the same response.
"""

    elif stage == "eligibility_screening":
        order = []
        if confirmed_fields.get("age_18_plus") is not True:
            order.append("Ask: Are you 18 years of age or older?")
        if confirmed_fields.get("has_internet") is not True:
            order.append("Ask: Do you have a stable internet connection for online classes?")
        if confirmed_fields.get("has_device") is not True:
            order.append("Ask: Do you have a laptop, tablet, or another suitable device to take classes?")
        if confirmed_fields.get("accepts_unpaid_role") is not True:
            order.append("Ask: This is a volunteer, unpaid role. Are you comfortable with that?")

        next_prompt = order[0] if order else "If all checks are complete, warmly acknowledge that and move ahead."
        return f"""CURRENT STAGE: Eligibility Screening

Your task: Ask only the next eligibility question and wait for the volunteer's answer.
Eligibility checks:
- above 18 years
- internet access
- suitable device
- clear understanding that this is an unpaid volunteer role

Next question:
{next_prompt}
"""

    elif stage == "contact_capture":
        name = confirmed_fields.get("full_name")
        phone = confirmed_fields.get("phone")
        email = confirmed_fields.get("email")
        if not name:
            return """CURRENT STAGE: Contact Details

Your task: Ask for the volunteer's full name in a warm, natural way.
"""
        if not phone:
            return f"""CURRENT STAGE: Contact Details

We know their name: {name}

Your task: Thank them and ask for their phone number.
"""
        if not email:
            return f"""CURRENT STAGE: Contact Details

We know their name and phone number.

Your task: Ask for their email address so the team can stay in touch.
"""
        return """CURRENT STAGE: Contact Details

Your task: Thank them for sharing their contact details and smoothly move to the next step.
"""

    elif stage == "teaching_profile":
        return """CURRENT STAGE: Registration Review

Your task: If a legacy session lands here, do not ask about teaching details.
Warmly acknowledge the volunteer and move to a quick registration review instead.
"""

    elif stage == "registration_review":
        # Summarize what we know
        summary = _build_profile_summary(confirmed_fields)
        return f"""CURRENT STAGE: Registration Review

What we've learned:
{summary}

Your task: Present the summary warmly and ask whether everything looks right or if they would like to update any contact detail before registration.
Do not sound transactional or bureaucratic.
"""
    
    elif stage == "onboarding_complete":
        name = confirmed_fields.get("full_name", "")
        return f"""CURRENT STAGE: Registration Complete

Your task: Thank {name} warmly and let them know their registration details have been received and the team will take the next step from here.
Be positive, brief, and reassuring.
"""
    
    elif stage == "human_review":
        return """CURRENT STAGE: Review Pending

Your task: Be warm and respectful. Say that the team will review the details and get back shortly.
Do not say they are ineligible, rejected, or disqualified.
"""

    elif stage == "paused":
        return """CURRENT STAGE: Paused

The volunteer wants to pause. Be understanding and let them know they can return anytime.
Example: "Of course! Take all the time you need. When you're ready to continue, I'll be here. Take care!"
"""
    
    return """Your task: Continue the conversation naturally, helping the volunteer feel welcome and gathering information about how they can contribute."""


def _get_field_collection_guidance(missing_fields: List[str], confirmed_fields: Dict) -> str:
    """Generate guidance for collecting missing fields."""
    
    if not missing_fields:
        return "All essential information has been collected. Focus on confirming and wrapping up."
    
    # Prioritize which field to collect next
    priority_order = [
        "video_acknowledgement",
        "age_18_plus",
        "has_internet",
        "has_device",
        "accepts_unpaid_role",
        "full_name",
        "phone",
        "email",
    ]
    next_field = None
    for field in priority_order:
        if field in missing_fields:
            next_field = field
            break
    
    if not next_field:
        next_field = missing_fields[0]
    
    field_prompts = {
        "video_acknowledgement": "Ask them to reply when they are ready to continue after the video.",
        "age_18_plus": "Ask politely whether they are 18 years of age or older.",
        "has_internet": "Ask whether they have a stable internet connection for online classes.",
        "has_device": "Ask whether they have a suitable device such as a laptop or tablet.",
        "accepts_unpaid_role": "Clearly mention that this is an unpaid volunteer role and ask if they are comfortable with that.",
        "full_name": "Ask for their name in a friendly, natural way.",
        "phone": "Ask for their phone number so the team can reach them easily.",
        "email": "Ask for their email address so you can stay connected.",
        "location": "Ask where they're based - this helps with scheduling and matching.",
        "interests": "Learn what areas of education interest them most.",
    }
    
    guidance = f"""INFORMATION TO GATHER:
Still needed: {', '.join(missing_fields)}
Already confirmed: {list(confirmed_fields.keys()) if confirmed_fields else 'None yet'}

Priority: {field_prompts.get(next_field, f'Ask about {next_field} naturally.')}
"""
    return guidance


def _build_profile_summary(confirmed_fields: Dict) -> str:
    """Build a natural language summary of the volunteer's profile."""
    parts = []
    
    if confirmed_fields.get("full_name"):
        parts.append(f"Name: {confirmed_fields['full_name']}")
    if confirmed_fields.get("phone"):
        parts.append(f"Phone: {confirmed_fields['phone']}")
    if confirmed_fields.get("email"):
        parts.append(f"Email: {confirmed_fields['email']}")
    if confirmed_fields.get("location"):
        parts.append(f"Location: {confirmed_fields['location']}")
    if confirmed_fields.get("age_18_plus") is not None:
        parts.append(f"18+ confirmed: {'Yes' if confirmed_fields['age_18_plus'] else 'Needs review'}")
    if confirmed_fields.get("has_internet") is not None:
        parts.append(f"Internet access: {'Yes' if confirmed_fields['has_internet'] else 'Needs review'}")
    if confirmed_fields.get("has_device") is not None:
        parts.append(f"Device access: {'Yes' if confirmed_fields['has_device'] else 'Needs review'}")
    if confirmed_fields.get("accepts_unpaid_role") is not None:
        parts.append(f"Understands unpaid role: {'Yes' if confirmed_fields['accepts_unpaid_role'] else 'Needs review'}")
    
    return "\n".join(parts) if parts else "No information collected yet"


# ============ LLM Provider Classes ============

class LLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        user_message: str
    ) -> str:
        """Generate a response from the LLM"""
        pass


class ClaudeProvider(LLMProvider):
    """Claude (Anthropic) provider using emergentintegrations"""
    
    def __init__(self):
        self.api_key = os.environ.get("EMERGENT_LLM_KEY")
        self.model = os.environ.get("LLM_MODEL", "claude-sonnet-4-5-20250929")
        
    async def generate(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        user_message: str
    ) -> str:
        if not self.api_key:
            logger.warning("No API key - using fallback response")
            return self._fallback_response(user_message)
        
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            
            chat = LlmChat(
                api_key=self.api_key,
                session_id=f"onboarding-{id(self)}",
                system_message=system_prompt
            )
            chat.with_model("anthropic", self.model)
            
            # Build context from history
            context = ""
            if messages:
                for msg in messages[-5:]:
                    role = "Volunteer" if msg["role"] == "user" else "eVidyaloka"
                    context += f"{role}: {msg['content']}\n"
            
            full_message = f"{context}\nVolunteer: {user_message}" if context else user_message
            user_msg = UserMessage(text=full_message)
            response = await chat.send_message(user_msg)
            
            return response
            
        except Exception as e:
            logger.error(f"LLM Error: {e}")
            return self._fallback_response(user_message)
    
    def _fallback_response(self, user_message: str) -> str:
        """Fallback response when LLM is unavailable"""
        return "Welcome to eVidyaloka! We're so glad you're interested in supporting education for children in rural India. What brings you to volunteer with us today?"


class OpenAIProvider(LLMProvider):
    """OpenAI provider using emergentintegrations"""
    
    def __init__(self):
        self.api_key = os.environ.get("EMERGENT_LLM_KEY")
        self.model = os.environ.get("LLM_MODEL", "gpt-5.2")
        
    async def generate(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        user_message: str
    ) -> str:
        if not self.api_key:
            return "Welcome to eVidyaloka! We're excited you want to help bring quality education to children who need it most."
        
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            
            chat = LlmChat(
                api_key=self.api_key,
                session_id=f"onboarding-{id(self)}",
                system_message=system_prompt
            )
            chat.with_model("openai", self.model)
            
            context = ""
            if messages:
                for msg in messages[-5:]:
                    role = "Volunteer" if msg["role"] == "user" else "eVidyaloka"
                    context += f"{role}: {msg['content']}\n"
            
            full_message = f"{context}\nVolunteer: {user_message}" if context else user_message
            user_msg = UserMessage(text=full_message)
            response = await chat.send_message(user_msg)
            
            return response
            
        except Exception as e:
            logger.error(f"LLM Error: {e}")
            return "Welcome to eVidyaloka! We're excited you want to help bring quality education to children who need it most."


class GeminiProvider(LLMProvider):
    """Gemini provider using emergentintegrations"""
    
    def __init__(self):
        self.api_key = os.environ.get("EMERGENT_LLM_KEY")
        self.model = os.environ.get("LLM_MODEL", "gemini-3-flash-preview")
        
    async def generate(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        user_message: str
    ) -> str:
        if not self.api_key:
            return "Welcome to eVidyaloka! We're thrilled to have you join our mission to support rural education."
        
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            
            chat = LlmChat(
                api_key=self.api_key,
                session_id=f"onboarding-{id(self)}",
                system_message=system_prompt
            )
            chat.with_model("gemini", self.model)
            
            context = ""
            if messages:
                for msg in messages[-5:]:
                    role = "Volunteer" if msg["role"] == "user" else "eVidyaloka"
                    context += f"{role}: {msg['content']}\n"
            
            full_message = f"{context}\nVolunteer: {user_message}" if context else user_message
            user_msg = UserMessage(text=full_message)
            response = await chat.send_message(user_msg)
            
            return response
            
        except Exception as e:
            logger.error(f"LLM Error: {e}")
            return "Welcome to eVidyaloka! We're thrilled to have you join our mission to support rural education."


# ============ Main LLM Adapter ============

class LLMAdapter:
    """
    Main adapter for LLM integration with enhanced prompting.
    """
    
    PROVIDERS = {
        "claude": ClaudeProvider,
        "openai": OpenAIProvider,
        "gemini": GeminiProvider,
    }
    
    def __init__(self):
        provider_name = os.environ.get("LLM_PROVIDER", "claude").lower()
        provider_class = self.PROVIDERS.get(provider_name, ClaudeProvider)
        self.provider = provider_class()
        logger.info(f"LLM Adapter initialized with provider: {provider_name}")
    
    async def generate_response(
        self,
        stage: str,
        messages: List[Dict[str, str]],
        user_message: str,
        missing_fields: List[str] = None,
        confirmed_fields: Dict = None,
        memory_context: str = None
    ) -> str:
        """
        Generate a response using contextual prompting.
        
        Args:
            stage: Current onboarding stage
            messages: Conversation history
            user_message: User's latest message
            missing_fields: Fields still needed
            confirmed_fields: Fields already collected
            memory_context: Memory context from previous conversations
            
        Returns:
            Assistant's response
        """
        missing_fields = missing_fields or []
        confirmed_fields = confirmed_fields or {}
        
        # Build contextual system prompt with memory
        system_prompt = build_system_prompt(
            stage=stage,
            missing_fields=missing_fields,
            confirmed_fields=confirmed_fields,
            conversation_length=len(messages),
            memory_context=memory_context
        )
        
        return await self.provider.generate(system_prompt, messages, user_message)
    
    async def generate_response_legacy(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        user_message: str
    ) -> str:
        """
        Legacy method for backward compatibility.
        """
        return await self.provider.generate(system_prompt, messages, user_message)


# Singleton instance
llm_adapter = LLMAdapter()
