# SERVE AI Platform

A multi-agent volunteer management platform designed to support the lifecycle of volunteers and needs in the SERVE ecosystem.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        SERVE AI Platform                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────┐     ┌─────────────────┐     ┌────────────────┐ │
│  │  serve-ui   │────▶│ serve-orchestrator│───▶│ serve-agents   │ │
│  │   (React)   │     │    (FastAPI)      │     │   (FastAPI)    │ │
│  └─────────────┘     └─────────────────┘     └────────────────┘ │
│         │                    │                       │           │
│         │                    │                       │           │
│         │                    ▼                       ▼           │
│         │           ┌─────────────────────────────────┐         │
│         │           │    serve-agentic-mcp-service    │         │
│         │           │          (FastAPI)              │         │
│         │           └─────────────────────────────────┘         │
│         │                        │                               │
│         │                        ▼                               │
│         │              ┌─────────────────┐                      │
│         └─────────────▶│    PostgreSQL   │                      │
│                        └─────────────────┘                      │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| serve-ui | 3000 | React frontend with role-based views |
| serve-orchestrator | 8001 | Central coordination layer |
| serve-onboarding-agent | 8003 | Onboarding agent service |
| serve-agentic-mcp-service | 8002 | MCP capability server (DB owner) |
| PostgreSQL | 5432 | Database |

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

### Local Development

#### Backend Services

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql+asyncpg://serve:serve@localhost:5432/serve_db"
export EMERGENT_LLM_KEY="your-key-here"
export LLM_PROVIDER="claude"
export LLM_MODEL="claude-sonnet-4-5-20250929"

# Run the server
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

#### Frontend

```bash
cd frontend

# Install dependencies
yarn install

# Set environment variables
export REACT_APP_BACKEND_URL="http://localhost:8001"

# Start development server
yarn start
```

## API Endpoints

### Orchestrator (`/api/orchestrator`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/interact` | POST | Process chat interaction |
| `/session/{id}` | GET | Get session state |
| `/sessions` | GET | List all sessions |
| `/health` | GET | Health check |

### MCP Service (`/api/mcp/capabilities/onboarding`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/start-session` | POST | Create new session |
| `/resume-context` | POST | Resume existing session |
| `/advance-state` | POST | Advance to next state |
| `/save-confirmed-fields` | POST | Save profile fields |
| `/get-missing-fields` | POST | Get missing required fields |
| `/session/{id}` | GET | Get full session |
| `/sessions` | GET | List all sessions |
| `/telemetry/{id}` | GET | Get telemetry events |

### Onboarding Agent (`/api/agents/onboarding`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/turn` | POST | Process agent turn |
| `/health` | GET | Health check |

## Views

### Volunteer View
- Chat interface for volunteer interaction
- Journey progress indicator
- Profile summary panel

### Ops/Coordinator View
- Volunteer pipeline (Kanban-style)
- Session status tracking
- Quick stats dashboard

### Tech Admin View
- Session browser
- Telemetry events viewer
- Conversation logs
- Raw JSON data viewer

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

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | - |
| `EMERGENT_LLM_KEY` | LLM API key | - |
| `LLM_PROVIDER` | LLM provider (claude/openai/gemini) | claude |
| `LLM_MODEL` | Model name | claude-sonnet-4-5-20250929 |
| `MCP_SERVICE_URL` | MCP service URL | http://localhost:8001/api/mcp |
| `CORS_ORIGINS` | Allowed CORS origins | * |

## Future Agents

The architecture supports adding these agents following the same pattern:

- Selection Agent
- Engagement Agent
- Need Agent
- Fulfillment Agent
- Delivery Assistant

## Tech Stack

- **Frontend**: React, Tailwind CSS, shadcn/ui
- **Backend**: Python, FastAPI
- **Database**: PostgreSQL with SQLAlchemy
- **LLM**: Claude Sonnet 4.5 (configurable)
- **Infrastructure**: Docker Compose

## License

Digital Public Good - DPGA Aligned
