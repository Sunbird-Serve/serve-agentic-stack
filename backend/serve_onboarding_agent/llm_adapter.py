"""
SERVE AI - LLM Adapter Layer
Configurable LLM integration with provider abstraction
"""
import os
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from dotenv import load_dotenv

load_dotenv()


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
            return self._fallback_response(user_message)
        
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            
            # Create chat instance
            chat = LlmChat(
                api_key=self.api_key,
                session_id=f"onboarding-{id(self)}",
                system_message=system_prompt
            )
            
            # Configure for Claude
            chat.with_model("anthropic", self.model)
            
            # Build context from history
            context = ""
            if messages:
                for msg in messages[-5:]:  # Last 5 messages for context
                    role = "User" if msg["role"] == "user" else "Assistant"
                    context += f"{role}: {msg['content']}\n"
            
            # Create message with context
            full_message = f"{context}\nUser: {user_message}" if context else user_message
            
            user_msg = UserMessage(text=full_message)
            response = await chat.send_message(user_msg)
            
            return response
            
        except Exception as e:
            print(f"LLM Error: {e}")
            return self._fallback_response(user_message)
    
    def _fallback_response(self, user_message: str) -> str:
        """Fallback response when LLM is unavailable"""
        return "Thank you for your message! I'm here to help you with the volunteer onboarding process. Could you tell me a bit about yourself and what motivates you to volunteer?"


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
            return "Thank you for reaching out! I'm here to help with your volunteer onboarding."
        
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
                    role = "User" if msg["role"] == "user" else "Assistant"
                    context += f"{role}: {msg['content']}\n"
            
            full_message = f"{context}\nUser: {user_message}" if context else user_message
            user_msg = UserMessage(text=full_message)
            response = await chat.send_message(user_msg)
            
            return response
            
        except Exception as e:
            print(f"LLM Error: {e}")
            return "Thank you for reaching out! I'm here to help with your volunteer onboarding."


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
            return "Thank you for reaching out! I'm here to help with your volunteer onboarding."
        
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
                    role = "User" if msg["role"] == "user" else "Assistant"
                    context += f"{role}: {msg['content']}\n"
            
            full_message = f"{context}\nUser: {user_message}" if context else user_message
            user_msg = UserMessage(text=full_message)
            response = await chat.send_message(user_msg)
            
            return response
            
        except Exception as e:
            print(f"LLM Error: {e}")
            return "Thank you for reaching out! I'm here to help with your volunteer onboarding."


class LLMAdapter:
    """
    Main adapter for LLM integration.
    Configurable through environment variables.
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
        
    async def generate_response(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        user_message: str
    ) -> str:
        """Generate a response using the configured LLM provider"""
        return await self.provider.generate(system_prompt, messages, user_message)


# Singleton instance
llm_adapter = LLMAdapter()
