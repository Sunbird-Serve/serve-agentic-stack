"""
SERVE MCP Server - Tools Package
MCP tool definitions are in main.py using FastMCP decorators.
This package provides additional utilities for tool management.
"""

# Tool metadata for documentation
TOOL_CATEGORIES = {
    "session": {
        "description": "Session lifecycle management",
        "tools": ["start_session", "get_session", "resume_session", "advance_session_state"]
    },
    "profile": {
        "description": "Volunteer profile management",
        "tools": ["get_missing_fields", "save_volunteer_fields", "get_volunteer_profile", "evaluate_readiness"]
    },
    "message": {
        "description": "Conversation message management",
        "tools": ["save_message", "get_conversation"]
    },
    "memory": {
        "description": "Long-term conversation memory",
        "tools": ["save_memory_summary", "get_memory_summary"]
    },
    "telemetry": {
        "description": "Event logging and analytics",
        "tools": ["log_event"]
    }
}

def get_tool_category(tool_name: str) -> str:
    """Get the category for a tool."""
    for category, info in TOOL_CATEGORIES.items():
        if tool_name in info["tools"]:
            return category
    return "other"
