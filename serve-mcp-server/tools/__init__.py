"""
SERVE MCP Server - Tools Package
MCP tool definitions are in main.py using FastMCP decorators.
This package provides tool category metadata for documentation and routing.
"""
from typing import Dict, List

TOOL_CATEGORIES: Dict[str, Dict] = {
    "identity": {
        "description": "Cross-channel actor identity resolution (S1–S5 scenarios)",
        "tools": ["lookup_actor"],
    },
    "session": {
        "description": "Session lifecycle management — create, resume, advance, list",
        "tools": [
            "start_session",
            "get_session",
            "resume_session",
            "advance_session_state",
            "list_sessions",
        ],
    },
    "profile": {
        "description": "Volunteer profile management (MCP DB working copy, write-back on complete)",
        "tools": [
            "get_missing_fields",
            "save_volunteer_fields",
            "get_volunteer_profile",
            "evaluate_readiness",
        ],
    },
    "conversation": {
        "description": "Conversation message persistence to MCP DB",
        "tools": ["save_message", "get_conversation"],
    },
    "memory": {
        "description": "Long-term conversation memory summaries (persisted to DB)",
        "tools": ["save_memory_summary", "get_memory_summary"],
    },
    "telemetry": {
        "description": "Telemetry, audit events and agent handoff logging",
        "tools": ["log_event", "emit_handoff_event"],
    },
    "coordinator": {
        "description": "Need coordinator identity — resolves and creates in Serve Registry",
        "tools": [
            "resolve_coordinator_identity",
            "create_coordinator",
            "map_coordinator_to_school",
        ],
    },
    "school": {
        "description": "School / entity management — delegates to Serve Need Service",
        "tools": [
            "resolve_school_context",
            "create_school_context",
            "fetch_previous_need_context",
        ],
    },
    "need": {
        "description": "Need lifecycle — draft in MCP DB, submit to Serve Need Service",
        "tools": [
            "start_need_session",
            "resume_need_context",
            "advance_need_state",
            "create_or_update_need_draft",
            "get_missing_need_fields",
            "evaluate_need_submission_readiness",
            "submit_need_for_approval",
            "update_need_status",
            "prepare_fulfillment_handoff",
            "pause_need_session",
            "save_need_message",
            "log_need_event",
            "emit_need_handoff_event",
        ],
    },
    "observability": {
        "description": "Server health, session analytics and registry sync status",
        "tools": [
            "get_server_health",
            "get_session_analytics",
            "get_registry_sync_status",
        ],
    },
}

PROMPT_REGISTRY: Dict[str, str] = {
    "volunteer_onboarding_prompt": "System prompt for the Volunteer Onboarding Agent",
    "need_coordinator_prompt":     "System prompt for the Need Coordination Agent",
    "memory_summarizer_prompt":    "System prompt for the Memory Summarizer Agent",
    "returning_volunteer_prompt":  "System prompt for the Returning Volunteer Engagement Agent",
}


def get_tool_category(tool_name: str) -> str:
    """Return the category name for a given tool, or 'other' if unknown."""
    for category, info in TOOL_CATEGORIES.items():
        if tool_name in info["tools"]:
            return category
    return "other"


def all_tool_names() -> List[str]:
    """Return a flat list of every registered tool name."""
    names: List[str] = []
    for info in TOOL_CATEGORIES.values():
        names.extend(info["tools"])
    return names
