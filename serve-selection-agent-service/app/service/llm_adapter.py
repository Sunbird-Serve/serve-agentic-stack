"""
SERVE Selection Agent Service - LLM Adapter (stub)

Optional LLM-based evaluation for nuanced profile assessment.
Contributor can use this for soft-skill evaluation, motivation scoring, etc.

If pure rule-based evaluation is sufficient, this module can be skipped entirely.
"""
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SelectionLLMAdapter:
    """Stub — contributor implements if LLM-based evaluation is needed."""

    def __init__(self) -> None:
        self._api_key: Optional[str] = (
            os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("EMERGENT_LLM_KEY")
        )
        self._model: str = os.environ.get("LLM_MODEL", "claude-sonnet-4-5-20250929")
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self._api_key:
                return None
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
            except ImportError:
                logger.warning("anthropic package not installed")
        return self._client

    async def evaluate_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """
        TODO (contributor): LLM-based profile evaluation.

        Example use cases:
        - Assess motivation from onboarding conversation summary
        - Score communication quality from key_facts
        - Flag potential concerns

        Returns:
            {"score": 0.0-1.0, "flags": [...], "reasoning": "..."}
        """
        # Stub — returns neutral score
        return {"score": 0.5, "flags": [], "reasoning": "stub — not yet implemented"}


# Singleton
llm_adapter = SelectionLLMAdapter()
