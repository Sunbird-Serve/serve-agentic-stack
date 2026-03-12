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
    
    if stage == "init":
        return """CURRENT STAGE: Welcome
        
Your task: Give a warm, brief welcome and ask what brings them to volunteer with eVidyaloka.
Example tone: "Welcome! It's wonderful to meet someone interested in supporting education. What brings you to eVidyaloka?"
"""
    
    elif stage == "intent_discovery":
        return """CURRENT STAGE: Understanding Their Interest

Your task: Learn why they want to volunteer and what impact they hope to make.
- Acknowledge their motivation warmly
- Ask about their connection to education or helping children
- Listen for clues about their skills and interests
Example: "That's really thoughtful. What draws you specifically to education or working with children?"
"""
    
    elif stage == "purpose_orientation":
        return """CURRENT STAGE: Sharing Our Mission

Your task: Briefly share what eVidyaloka does and how volunteers contribute.
- Explain simply: we connect volunteers with rural students who need learning support
- Mention that volunteers can teach, mentor, or support in various ways
- Ask what kind of support they'd be interested in providing
Example: "At eVidyaloka, volunteers like you teach and mentor children in villages who might not otherwise have access to quality education. What kind of support would you enjoy providing?"
"""
    
    elif stage == "eligibility_confirmation":
        # Check what we still need
        name = confirmed_fields.get("full_name")
        email = confirmed_fields.get("email")
        
        if not name:
            return """CURRENT STAGE: Getting to Know You

Your task: Ask for their name in a friendly way.
Example: "I'd love to know who I'm chatting with! What's your name?"
"""
        elif not email:
            return f"""CURRENT STAGE: Getting to Know You

Their name: {name}

Your task: Thank them and ask for their email address.
Example: "Nice to meet you, {name}! Could you share your email address so we can stay in touch?"
"""
        else:
            return f"""CURRENT STAGE: Getting to Know You

We know: {name}, {email}

Your task: Ask about their location or any other missing basic info.
"""
    
    elif stage == "capability_discovery":
        return """CURRENT STAGE: Learning About Their Strengths

Your task: Explore their skills and availability.
- Ask about subjects they could teach or skills they have
- Understand their time availability
- Be encouraging about whatever they share
Example: "What subjects or skills do you feel comfortable sharing with students? Even everyday skills can make a big difference!"
"""
    
    elif stage == "profile_confirmation":
        # Summarize what we know
        summary = _build_profile_summary(confirmed_fields)
        return f"""CURRENT STAGE: Confirming Their Profile

What we've learned:
{summary}

Your task: Present this summary warmly and ask if anything needs to be updated.
Keep it conversational - don't list everything robotically.
Example: "Let me make sure I have this right - [summarize naturally]. Does that sound correct, or would you like to update anything?"
"""
    
    elif stage == "onboarding_complete":
        name = confirmed_fields.get("full_name", "")
        return f"""CURRENT STAGE: Welcome Complete!

Your task: Congratulate {name} on completing the onboarding.
- Express genuine excitement about them joining
- Let them know what happens next (we'll match them with students)
- Thank them for their willingness to help
Keep it warm but brief - don't over-celebrate.
Example: "Wonderful, {name}! You're all set to begin your journey with eVidyaloka. We'll be in touch soon to connect you with students who'll benefit from your support. Thank you for choosing to make a difference!"
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
    priority_order = ["full_name", "email", "skills", "availability", "location"]
    next_field = None
    for field in priority_order:
        if field in missing_fields:
            next_field = field
            break
    
    if not next_field:
        next_field = missing_fields[0]
    
    field_prompts = {
        "full_name": "Ask for their name in a friendly, natural way.",
        "email": "Ask for their email address so you can stay connected.",
        "skills": "Explore what subjects or skills they could share with students.",
        "availability": "Understand how much time they can dedicate (hours per week, preferred days).",
        "location": "Ask where they're based - this helps with scheduling and matching.",
        "phone": "Optionally ask if they'd like to share a phone number for coordination.",
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
    if confirmed_fields.get("email"):
        parts.append(f"Email: {confirmed_fields['email']}")
    if confirmed_fields.get("location"):
        parts.append(f"Location: {confirmed_fields['location']}")
    if confirmed_fields.get("skills"):
        skills = confirmed_fields["skills"]
        if isinstance(skills, list):
            parts.append(f"Skills: {', '.join(skills)}")
        else:
            parts.append(f"Skills: {skills}")
    if confirmed_fields.get("availability"):
        parts.append(f"Availability: {confirmed_fields['availability']}")
    
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
