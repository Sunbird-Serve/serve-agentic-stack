"""
Shared fixtures for onboarding agent evals.
"""
import sys
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

# Ensure the service root is on sys.path so `app.*` imports work
SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

# Set required env vars before any app imports
os.environ.setdefault("MCP_SERVER_URL", "http://localhost:8004")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("LLM_MODEL", "claude-haiku-4-5-20251001")
os.environ.setdefault("KEYCLOAK_URL", "http://localhost:8080")
os.environ.setdefault("KEYCLOAK_REALM", "sunbird-serve")


@pytest.fixture
def session_id():
    return uuid4()


@pytest.fixture
def base_session_state(session_id):
    """Minimal SessionState dict for constructing AgentTurnRequest."""
    from app.schemas import SessionState
    return SessionState(
        id=session_id,
        channel="web_ui",
        persona="new_volunteer",
        workflow="new_volunteer_onboarding",
        active_agent="onboarding",
        status="active",
        stage="welcome",
        sub_state=None,
    )


@pytest.fixture
def mock_domain_client(monkeypatch):
    """
    Mock the domain_client module-level singleton so no real MCP calls are made.
    Returns the mock so tests can inspect calls.
    """
    from app.clients import domain_client as dc_module

    mock = AsyncMock()
    mock.get_missing_fields.return_value = {
        "data": {"missing_fields": [], "confirmed_fields": {}}
    }
    mock.save_confirmed_fields.return_value = {"status": "success"}
    mock.advance_state.return_value = {"status": "success"}
    mock.save_message.return_value = {"status": "success"}
    mock.log_event.return_value = {"status": "success"}
    mock.emit_handoff_event.return_value = {"status": "success"}
    mock.save_memory_summary.return_value = {"status": "success"}
    mock.get_memory_summary.return_value = {"status": "success", "data": None}
    mock.create_volunteer_record.return_value = {"status": "success", "volunteer": {"id": str(uuid4())}}
    mock.merge_volunteer_facts.return_value = {"status": "success"}
    mock.find_volunteer.return_value = {"status": "not_found"}

    monkeypatch.setattr("app.clients.domain_client", mock)
    # Also patch inside onboarding_logic which imports at module level
    monkeypatch.setattr("app.service.onboarding_logic.domain_client", mock)

    return mock


@pytest.fixture
def mock_llm_adapter(monkeypatch):
    """
    Mock the LLM adapter so no real LLM calls are made.
    Returns the mock so tests can set return values per scenario.
    """
    mock = AsyncMock()
    mock.generate_response.return_value = "Mock LLM response"

    monkeypatch.setattr("app.service.onboarding_logic.llm_adapter", mock)

    return mock
