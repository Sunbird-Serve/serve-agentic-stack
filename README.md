# SERVE AI Platform

A multi-agent volunteer management platform designed to support the lifecycle of volunteers and needs in the SERVE ecosystem. Built as a Digital Public Good aligned with DPGA.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          SERVE AI Platform                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐                                                       │
│  │ serve-ai-ui  │ (React - Port 3000)                                   │
│  │   Frontend   │                                                       │
│  └──────┬───────┘                                                       │
│         │ HTTP                                                          │
│         ▼                                                               │
│  ┌──────────────────┐                                                   │
│  │ serve-orchestrator│ (FastAPI - Port 8001)                            │
│  │  Coordination     │                                                   │
│  └──────┬───────────┘                                                   │
│         │ HTTP                                                          │
│         ▼                                                               │
│  ┌────────────────────────────┐                                         │
│  │ serve-onboarding-agent-    │ (FastAPI - Port 8002)                   │
│  │ service                    │                                         │
│  │ (+ future agent services)  │                                         │
│  └──────┬─────────────────────┘                                         │
│         │ HTTP                                                          │
│         ▼                                                               │
│  ┌────────────────────────────┐         ┌─────────────┐                 │
│  │ serve-agentic-mcp-service  │────────▶│  PostgreSQL │                 │
│  │ (FastAPI - Port 8003)      │         │  (Port 5432)│                 │
│  │ MCP Capabilities + DB      │         └─────────────┘                 │
│  └────────────────────────────┘                                         │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| serve-ai-ui | 3000 | React frontend with role-based views |
| serve-orchestrator | 8001 | Central coordination layer |
| serve-onboarding-agent-service | 8002 | Onboarding agent service |
| serve-agentic-mcp-service | 8003 | MCP capability server (DB owner) |
| PostgreSQL | 5432 | Database with persistent volume |

## Service Boundaries

### serve-orchestrator
- Channel-agnostic coordination layer
- Receives interaction requests from UI or channel adapters
- Resolves or creates sessions
- Determines workflow and active agent
- Routes requests to agent services via HTTP
- Does NOT perform conversational logic
- Does NOT access database directly

### serve-onboarding-agent-service
- Implements onboarding conversational logic
- Receives session context from orchestrator
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

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Node.js 18+ (for local frontend development)
- Python 3.11+ (for local backend development)

### Running with Docker Compose

```bash
# Clone the repository
git clone <repo-url>
cd serve-ai

# Create environment file
cp .env.example .env
# Edit .env and add your EMERGENT_LLM_KEY

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Access the application
open http://localhost:3000
```

### Running Services Individually

#### MCP Service (start first - owns database)

```bash
cd serve-agentic-mcp-service
pip install -r requirements.txt
export DATABASE_URL="postgresql+asyncpg://serve:servepassword@localhost:5432/serve_db"
uvicorn main:app --host 0.0.0.0 --port 8003 --reload
```

#### Onboarding Agent Service

```bash
cd serve-onboarding-agent-service
pip install -r requirements.txt
pip install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/
export MCP_SERVICE_URL="http://localhost:8003"
export EMERGENT_LLM_KEY="your-key"
uvicorn main:app --host 0.0.0.0 --port 8002 --reload
```

#### Orchestrator Service

```bash
cd serve-orchestrator
pip install -r requirements.txt
export MCP_SERVICE_URL="http://localhost:8003"
export ONBOARDING_AGENT_URL="http://localhost:8002"
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

#### Frontend

```bash
cd serve-ai-ui
yarn install
export REACT_APP_BACKEND_URL="http://localhost:8001"
yarn start
```

## API Endpoints

### Orchestrator (`http://localhost:8001/api`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/interact` | POST | Process chat interaction |
| `/session/{id}` | GET | Get session state |
| `/sessions` | GET | List all sessions |
| `/health` | GET | Health check |

### Onboarding Agent (`http://localhost:8002/api`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/turn` | POST | Process agent turn |
| `/health` | GET | Health check |

### MCP Service (`http://localhost:8003/api/capabilities/onboarding`)

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

### Core Entities

| Table | Description |
|-------|-------------|
| sessions | Interaction lifecycle tracking |
| session_events | State transitions and routing decisions |
| volunteer_profiles | Volunteer information |
| conversation_messages | Chat history |
| memory_summaries | Long-term context summaries |
| handoff_events | Agent transitions |
| telemetry_events | Operational telemetry |

## Onboarding States

| State | Description |
|-------|-------------|
| `init` | Initial welcome state |
| `intent_discovery` | Understanding volunteer motivation |
| `purpose_orientation` | Introducing SERVE program |
| `eligibility_confirmation` | Gathering basic info |
| `capability_discovery` | Exploring skills & availability |
| `profile_confirmation` | Reviewing collected information |
| `onboarding_complete` | Onboarding finished |
| `paused` | Session paused |

## Environment Variables

### Orchestrator
| Variable | Description |
|----------|-------------|
| `MCP_SERVICE_URL` | URL to MCP service |
| `ONBOARDING_AGENT_URL` | URL to onboarding agent |
| `CORS_ORIGINS` | Allowed CORS origins |

### Onboarding Agent
| Variable | Description |
|----------|-------------|
| `MCP_SERVICE_URL` | URL to MCP service |
| `LLM_PROVIDER` | LLM provider (claude/openai/gemini) |
| `LLM_MODEL` | Model name |
| `EMERGENT_LLM_KEY` | LLM API key |

### MCP Service
| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `CORS_ORIGINS` | Allowed CORS origins |

## Future Agents

The architecture supports adding these agents as separate services:

- serve-selection-agent-service
- serve-engagement-agent-service
- serve-need-agent-service
- serve-fulfillment-agent-service
- serve-delivery-assistant-service

Each would follow the same pattern:
1. Create service folder with FastAPI app
2. Implement agent logic calling MCP capabilities
3. Add to docker-compose
4. Register in orchestrator's agent client

## Tech Stack

- **Frontend**: React, Tailwind CSS, shadcn/ui
- **Backend**: Python 3.11, FastAPI
- **Database**: PostgreSQL with SQLAlchemy
- **LLM**: Claude Sonnet 4.5 (configurable)
- **Infrastructure**: Docker Compose

## License

Digital Public Good - DPGA Aligned
