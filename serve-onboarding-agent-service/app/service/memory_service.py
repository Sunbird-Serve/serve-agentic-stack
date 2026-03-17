"""
SERVE AI - Conversation Memory Summarization Service
Provides long-term memory through periodic conversation summarization.

This service enables:
1. Periodic summarization of conversation history
2. Key fact extraction from conversations
3. Context retrieval for returning volunteers
4. Personalized interactions based on past conversations
"""
import os
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from uuid import UUID

logger = logging.getLogger(__name__)


# ============ Summarization Prompts ============

SUMMARIZATION_PROMPT = """You are summarizing a volunteer onboarding conversation for eVidyaloka.

Create a brief, factual summary that captures:
1. The volunteer's background and motivation
2. Key information they shared (skills, availability, interests)
3. Their emotional tone and engagement level
4. Any specific preferences or concerns they mentioned

Keep the summary concise (2-3 sentences max) and focus on facts that would help continue the conversation naturally if they return later.

Conversation:
{conversation}

Summary:"""

KEY_FACTS_PROMPT = """Extract the key facts from this volunteer onboarding conversation.

Return a list of simple, factual statements about the volunteer. Each fact should be:
- Self-contained and understandable on its own
- Factual, not interpretive
- Useful for personalizing future conversations

Examples of good facts:
- "Wants to teach mathematics to children"
- "Available on weekends, 3-4 hours"
- "Has experience tutoring neighbors' children"
- "Motivated by personal experience with rural education"

Conversation:
{conversation}

Return ONLY the facts as a simple list, one per line, starting with a dash (-):"""


# ============ Memory Summarizer Class ============

class MemorySummarizer:
    """
    Handles conversation summarization using LLM.
    """
    
    def __init__(self):
        self.api_key = os.environ.get("EMERGENT_LLM_KEY")
        self.model = os.environ.get("LLM_MODEL", "claude-sonnet-4-5-20250929")
        self.summary_threshold = 6  # Summarize after this many messages
    
    async def should_summarize(self, message_count: int, last_summary_at: Optional[datetime] = None) -> bool:
        """
        Determine if a summary should be generated.
        
        Args:
            message_count: Number of messages in conversation
            last_summary_at: When the last summary was generated
            
        Returns:
            True if summarization is recommended
        """
        # Summarize after every N messages
        if message_count >= self.summary_threshold and message_count % self.summary_threshold == 0:
            return True
        
        # Also summarize if it's been a while since last summary
        if last_summary_at:
            hours_since = (datetime.utcnow() - last_summary_at).total_seconds() / 3600
            if hours_since > 24 and message_count > 3:
                return True
        
        return False
    
    async def generate_summary(self, conversation: List[Dict[str, str]]) -> Tuple[str, List[str]]:
        """
        Generate a summary and extract key facts from conversation.
        
        Args:
            conversation: List of message dictionaries with 'role' and 'content'
            
        Returns:
            Tuple of (summary_text, key_facts_list)
        """
        if not conversation:
            return "", []
        
        # Format conversation for the prompt
        formatted = self._format_conversation(conversation)
        
        # Generate summary
        summary = await self._call_llm(SUMMARIZATION_PROMPT.format(conversation=formatted))
        
        # Extract key facts
        facts_response = await self._call_llm(KEY_FACTS_PROMPT.format(conversation=formatted))
        key_facts = self._parse_facts(facts_response)
        
        return summary, key_facts
    
    async def generate_context_prompt(
        self,
        summary: str,
        key_facts: List[str],
        confirmed_fields: Dict[str, Any]
    ) -> str:
        """
        Generate a context prompt for the agent based on memory.
        
        Args:
            summary: Previous conversation summary
            key_facts: List of extracted key facts
            confirmed_fields: Currently confirmed profile fields
            
        Returns:
            Context string to include in agent prompts
        """
        if not summary and not key_facts:
            return ""
        
        context_parts = []
        
        if summary:
            context_parts.append(f"Previous conversation summary: {summary}")
        
        if key_facts:
            facts_str = "\n".join(f"  - {fact}" for fact in key_facts[:5])
            context_parts.append(f"Key facts about this volunteer:\n{facts_str}")
        
        if confirmed_fields:
            name = confirmed_fields.get("full_name")
            if name:
                context_parts.append(f"Remember: Their name is {name}. Use it naturally in conversation.")
        
        return "\n\n".join(context_parts)
    
    def _format_conversation(self, conversation: List[Dict[str, str]]) -> str:
        """Format conversation for LLM prompt."""
        formatted = []
        for msg in conversation[-10:]:  # Last 10 messages
            role = "Volunteer" if msg.get("role") == "user" else "eVidyaloka"
            content = msg.get("content", "")
            formatted.append(f"{role}: {content}")
        return "\n".join(formatted)
    
    def _parse_facts(self, response: str) -> List[str]:
        """Parse key facts from LLM response."""
        facts = []
        for line in response.strip().split("\n"):
            line = line.strip()
            if line.startswith("-"):
                fact = line[1:].strip()
                if fact and len(fact) > 5:
                    facts.append(fact)
        return facts[:10]  # Max 10 facts
    
    async def _call_llm(self, prompt: str) -> str:
        """Call LLM for summarization."""
        if not self.api_key:
            logger.warning("No API key for summarization - using fallback")
            return self._fallback_summary(prompt)
        
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            
            chat = LlmChat(
                api_key=self.api_key,
                session_id=f"memory-{id(self)}",
                system_message="You are a helpful assistant that summarizes conversations accurately and concisely."
            )
            chat.with_model("anthropic", self.model)
            
            response = await chat.send_message(UserMessage(text=prompt))
            return response
            
        except Exception as e:
            logger.error(f"LLM summarization error: {e}")
            return self._fallback_summary(prompt)
    
    def _fallback_summary(self, prompt: str) -> str:
        """Generate a basic fallback when LLM is unavailable."""
        if "Key facts" in prompt:
            return "- Interested in volunteering with eVidyaloka"
        return "Volunteer expressed interest in supporting education through eVidyaloka."


# ============ Memory Service Integration ============

class ConversationMemoryService:
    """
    Service for managing conversation memory and summaries.
    Integrates with MCP capabilities for persistence.
    """
    
    def __init__(self):
        self.summarizer = MemorySummarizer()
        self._summaries_cache: Dict[str, Dict] = {}  # In-memory cache for preview
    
    async def process_conversation_update(
        self,
        session_id: str,
        conversation: List[Dict[str, str]],
        domain_client = None
    ) -> Optional[Dict]:
        """
        Process a conversation update and generate summary if needed.
        
        Args:
            session_id: Session identifier
            conversation: Current conversation history
            domain_client: Domain client for persistence (optional)
            
        Returns:
            Summary data if generated, None otherwise
        """
        message_count = len(conversation)
        
        # Check if we have a recent summary
        last_summary = self._summaries_cache.get(session_id, {}).get("created_at")
        
        # Determine if we should summarize
        if not await self.summarizer.should_summarize(message_count, last_summary):
            return None
        
        # Generate summary
        summary_text, key_facts = await self.summarizer.generate_summary(conversation)
        
        if not summary_text:
            return None
        
        summary_data = {
            "session_id": session_id,
            "summary_text": summary_text,
            "key_facts": key_facts,
            "message_count": message_count,
            "created_at": datetime.utcnow()
        }
        
        # Cache locally
        self._summaries_cache[session_id] = summary_data
        
        # Persist via domain client if available
        if domain_client:
            try:
                await domain_client.save_memory_summary(
                    session_id=session_id,
                    summary_text=summary_text,
                    key_facts=key_facts
                )
            except Exception as e:
                logger.error(f"Failed to persist summary: {e}")
        
        logger.info(f"Generated memory summary for session {session_id[:8]}...: {len(key_facts)} facts")
        return summary_data
    
    async def get_memory_context(
        self,
        session_id: str,
        confirmed_fields: Dict[str, Any] = None,
        domain_client = None
    ) -> str:
        """
        Get memory context for an agent prompt.
        
        Args:
            session_id: Session identifier
            confirmed_fields: Currently confirmed profile fields
            domain_client: Domain client for retrieval (optional)
            
        Returns:
            Context string to include in agent prompts
        """
        summary_data = None
        
        # Try to get from domain service first
        if domain_client:
            try:
                result = await domain_client.get_memory_summary(session_id)
                if result.get("status") == "success" and result.get("data"):
                    summary_data = result["data"]
            except Exception as e:
                logger.debug(f"Could not get summary from domain service: {e}")
        
        # Fall back to cache
        if not summary_data:
            summary_data = self._summaries_cache.get(session_id)
        
        if not summary_data:
            return ""
        
        return await self.summarizer.generate_context_prompt(
            summary=summary_data.get("summary_text", ""),
            key_facts=summary_data.get("key_facts", []),
            confirmed_fields=confirmed_fields or {}
        )
    
    async def get_returning_volunteer_context(
        self,
        session_id: str,
        volunteer_name: str = None,
        domain_client = None
    ) -> str:
        """
        Generate a warm context for a returning volunteer.
        
        Args:
            session_id: Session identifier
            volunteer_name: Volunteer's name if known
            domain_client: Domain client for retrieval
            
        Returns:
            Welcome-back context for the agent
        """
        summary_data = self._summaries_cache.get(session_id)
        
        if not summary_data:
            if domain_client:
                try:
                    result = await domain_client.get_memory_summary(session_id)
                    if result.get("status") == "success":
                        summary_data = result.get("data")
                except:
                    pass
        
        if not summary_data:
            return ""
        
        key_facts = summary_data.get("key_facts", [])
        
        context = f"""This volunteer is returning to continue their conversation.

Previous context: {summary_data.get('summary_text', 'Had started onboarding')}
"""
        
        if volunteer_name:
            context += f"\nGreet them warmly by name ({volunteer_name}) and offer to continue where they left off."
        
        if key_facts:
            context += f"\n\nRemember these facts about them:\n"
            context += "\n".join(f"  - {fact}" for fact in key_facts[:3])
        
        return context


# Singleton instance
memory_service = ConversationMemoryService()
