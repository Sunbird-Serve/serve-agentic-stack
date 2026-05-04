# SERVE AI Platform

A multi-agent volunteer management platform designed to support the lifecycle of volunteers and needs in the SERVE ecosystem. Built as a Digital Public Good aligned with DPGA.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          SERVE AI Platform                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐                                                       │
│  │ serve-ai-ui  │  React Frontend                                       │
│  │  Port 3000   │                                                       │
│  └──────┬───────┘                                                       │
│         │ HTTP                                                          │
│         ▼                                                               │
│  ┌──────────────────┐                                                   │
│  │ serve-orchestrator│  Coordination Layer                              │
│  │    Port 8001      │                                                   │
│  └──────┬───────────┘                                                   │
│         │ HTTP                                                          │
│         ▼                                                               │
│  ┌────────────────────────────┐                                         │
│  │ serve-onboarding-agent-    │  Onboarding Agent                       │
│  │ service    Port 8002       │  (future agents added here)             │
│  └──────┬─────────────────────┘                                         │
│         │ HTTP                                                          │
│         ▼                                                               │
│  ┌────────────────────────────┐         ┌─────────────┐                 │
│  │ serve-agentic-mcp-service  │────────▶│  PostgreSQL │                 │
│  │        Port 8003           │         │  Port 5432  │                 │
│  │   MCP Capabilities + DB    │         └─────────────┘                 │
│  └────────────────────────────┘                                         │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
/app/
├── serve-ai-ui/                      # React Frontend
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── Dockerfile
│
├── serve-orchestrator/               # Coordination Service
│   ├── app/
│   │   ├── api/
│   │   ├── service/
│   │   ├── schemas/
│   │   └── clients/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
│
├── serve-onboarding-agent-service/   # Onboarding Agent
│   ├── app/
│   │   ├── api/
│   │   ├── service/
│   │   ├── schemas/
│   │   └── clients/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
│
├── serve-agentic-mcp-service/        # MCP + Database
│   ├── app/
│   │   ├── api/
│   │   ├── service/
│   │   ├── schemas/
│   │   ├── models/
│   │   └── db/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
│
├── docker-compose.yml                # All services + Postgres
├── .env.example                      # Environment template
└── README.md
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| serve-ai-ui | 3000 | React frontend with role-based views |
| serve-orchestrator | 8001 | Central coordination layer |
| serve-onboarding-agent-service | 8002 | Onboarding agent with LLM |
| serve-agentic-mcp-service | 8003 | MCP capabilities + database |
| postgres | 5432 | PostgreSQL with persistent volume |

## Quick Start

### Prerequisites

- Docker & Docker Compose

### Running

```bash
# Clone the repository
git clone <repo-url>
cd serve-ai

# Create environment file
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Access the application
open http://localhost:3000
```

### Stop Services

```bash
docker-compose down
```

### Reset Database

```bash
docker-compose down -v  # Removes volumes
docker-compose up -d
```

## Service Responsibilities

### serve-orchestrator
- Channel-agnostic coordination layer
- Receives interaction requests from UI or channel adapters
- Resolves or creates sessions via MCP
- Determines workflow and active agent
- Routes requests to agent services via HTTP
- Does NOT perform conversational logic
- Does NOT access database directly

### serve-onboarding-agent-service
- Implements onboarding conversational logic
- Receives session context from orchestrator
- Generates responses using LLM (Claude Sonnet 4.5)
- Calls MCP capabilities over HTTP
- Returns structured agent responses
- Does NOT access database directly

### serve-agentic-mcp-service
- Exposes domain capabilities as HTTP APIs
- Owns ALL database access and persistence
- Stores sessions, profiles, messages, events
- Returns structured capability responses

### serve-ai-ui
- React frontend with Tailwind CSS
- Role-based views (Volunteer, Ops, Admin)
- Calls orchestrator via HTTP

## API Endpoints

### Orchestrator (http://localhost:8001/api)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/interact` | POST | Process chat interaction |
| `/session/{id}` | GET | Get session state |
| `/sessions` | GET | List all sessions |
| `/health` | GET | Health check |

### Onboarding Agent (http://localhost:8002/api)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/turn` | POST | Process agent turn |
| `/health` | GET | Health check |

### MCP Service (http://localhost:8003/api/capabilities/onboarding)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/start-session` | POST | Create new session |
| `/resume-context` | POST | Resume existing session |
| `/advance-state` | POST | Advance to next state |
| `/save-confirmed-fields` | POST | Save profile fields |
| `/get-missing-fields` | POST | Get missing required fields |
| `/save-message` | POST | Save conversation message |
| `/log-event` | POST | Log telemetry event |
| `/session/{id}` | GET | Get full session |
| `/sessions` | GET | List all sessions |
| `/telemetry/{id}` | GET | Get telemetry events |

## Database Schema

### Core Tables

| Table | Description |
|-------|-------------|
| sessions | Interaction lifecycle tracking |
| session_events | State transitions and routing |
| volunteer_profiles | Volunteer information |
| conversation_messages | Chat history |
| memory_summaries | Long-term context |
| handoff_events | Agent transitions |
| telemetry_events | Operational telemetry |

## Onboarding States

| State | Description |
|-------|-------------|
| `init` | Initial welcome |
| `intent_discovery` | Understanding motivation |
| `purpose_orientation` | Introducing SERVE |
| `eligibility_confirmation` | Gathering basic info |
| `capability_discovery` | Exploring skills |
| `profile_confirmation` | Reviewing info |
| `onboarding_complete` | Finished |
| `paused` | Session paused |

## Environment Variables

### Root (.env)
```
ANTHROPIC_API_KEY=your-key-here
```

### serve-orchestrator
| Variable | Description |
|----------|-------------|
| `MCP_SERVICE_URL` | URL to MCP service |
| `ONBOARDING_AGENT_URL` | URL to onboarding agent |
| `CORS_ORIGINS` | Allowed CORS origins |

### serve-onboarding-agent-service
| Variable | Description |
|----------|-------------|
| `MCP_SERVICE_URL` | URL to MCP service |
| `LLM_PROVIDER` | LLM provider (claude/openai/gemini) |
| `LLM_MODEL` | Model name |
| `ANTHROPIC_API_KEY` | LLM API key |

### serve-agentic-mcp-service
| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `CORS_ORIGINS` | Allowed CORS origins |

## Adding Future Agents

To add a new agent (e.g., Selection Agent):

1. Create `serve-selection-agent-service/` following the onboarding pattern
2. Add service to `docker-compose.yml`
3. Register agent URL in orchestrator's agent client
4. Implement MCP capabilities for the new domain

## Tech Stack

- **Frontend**: React, Tailwind CSS, shadcn/ui
- **Backend**: Python 3.11, FastAPI
- **Database**: PostgreSQL with SQLAlchemy
- **LLM**: Claude Sonnet 4.5 (configurable)
- **Infrastructure**: Docker Compose

## License

Digital Public Good - DPGA Aligned
