# SERVE AI - MCP Server

Real Model Context Protocol (MCP) server for eVidyaloka volunteer management.

## Overview

This server implements the [Model Context Protocol](https://modelcontextprotocol.io/) 
using the official Python MCP SDK. It exposes volunteer management capabilities as 
MCP tools that can be called by any MCP-compatible client (Claude Desktop, Cursor, etc.).

## Installation

```bash
pip install mcp
```

## Running the Server

### Stdio Transport (for Claude Desktop, Cursor)
```bash
cd /app/serve-mcp-server
python main.py
```

### HTTP/SSE Transport (for web clients)
```bash
cd /app/serve-mcp-server
python main.py --http
```

## Available Tools

### Session Management
| Tool | Description |
|------|-------------|
| `start_session` | Start a new volunteer onboarding session |
| `get_session` | Retrieve session state |
| `resume_session` | Resume with full context (profile, history, memory) |
| `advance_session_state` | Progress to next onboarding stage |

### Profile Management
| Tool | Description |
|------|-------------|
| `get_missing_fields` | Get fields still needed from volunteer |
| `save_volunteer_fields` | Save confirmed profile fields |
| `get_volunteer_profile` | Get complete volunteer profile |
| `evaluate_readiness` | Check if ready for selection phase |

### Conversation
| Tool | Description |
|------|-------------|
| `save_message` | Save a conversation message |
| `get_conversation` | Get conversation history |

### Memory
| Tool | Description |
|------|-------------|
| `save_memory_summary` | Save conversation summary for long-term context |
| `get_memory_summary` | Retrieve memory summary |

### Telemetry
| Tool | Description |
|------|-------------|
| `log_event` | Log telemetry event for debugging |

## Example Usage

### With Claude Desktop

Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "serve-ai": {
      "command": "python",
      "args": ["/app/serve-mcp-server/main.py"]
    }
  }
}
```

### Programmatic Usage

```python
import asyncio
from main import start_session, save_volunteer_fields, get_missing_fields

async def onboard_volunteer():
    # Start session
    session = await start_session(channel="web_ui", persona="new_volunteer")
    session_id = session["session_id"]
    
    # Save volunteer info
    await save_volunteer_fields(session_id, {
        "full_name": "Priya",
        "email": "priya@example.com",
        "skills": ["teaching", "mathematics"]
    })
    
    # Check what's still needed
    result = await get_missing_fields(session_id)
    print(f"Missing: {result['missing_fields']}")
    print(f"Completion: {result['completion_percentage']}%")

asyncio.run(onboard_volunteer())
```

## Architecture

```
/app/serve-mcp-server/
├── main.py              # MCP server with tool definitions
├── services/            # Business logic services
│   ├── session_service.py
│   ├── profile_service.py
│   └── memory_service.py
└── tools/               # Tool utilities and metadata
```

The server follows a clean separation:
- **MCP Layer** (`main.py`): Tool definitions with typed schemas
- **Service Layer** (`services/`): Reusable business logic
- **Storage Layer**: Currently in-memory, easily swappable to Postgres

## Integration with Existing System

The MCP server can run alongside the existing HTTP services:
- **Production**: MCP server for LLM integration + HTTP for UI

## Future Work

- [ ] Connect services to Postgres instead of in-memory
- [ ] Add MCP Resources for read-only data access
- [ ] Add MCP Prompts for guided workflows
- [ ] SSE transport for web-based MCP clients
