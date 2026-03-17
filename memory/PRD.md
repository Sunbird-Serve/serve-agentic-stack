# SERVE AI - Product Requirements Document

## Original Problem Statement
Build the foundational scaffold for a SERVE AI multi-agent volunteer management platform with clean service boundaries - a Digital Public Good aligned with DPGA.

## Architecture (Current - Dec 2025)

```
/app/
├── serve-ai-ui/                    # React Frontend (Port 3000)
├── serve-orchestrator/             # Coordination Layer (Port 8001)
├── serve-onboarding-agent-service/ # Onboarding Agent (Port 8002)
├── serve-data-service/             # Data/Capability Service (Port 8003) [renamed from mcp]
├── serve-mcp-server/               # NEW: Real MCP Server (Protocol-compliant)
├── docker-compose.yml              # All services + Postgres
└── README.md
```

### Important: MCP Clarification
- **MCP = Model Context Protocol** - the standard protocol for LLM tool access
- **serve-mcp-server/** - Real MCP server using official Python SDK (`pip install mcp`)
- **serve-data-service/** - HTTP capability service (formerly misnamed "mcp-service")

### Service Communication
- UI → Orchestrator (HTTP)
- Orchestrator → Agent Services (HTTP)
- Agent Services → Data Service (HTTP) OR MCP Server (MCP Protocol)
- Data Service / MCP Server → PostgreSQL (Direct)

### Runtime
- **Preview**: Monolithic `/app/backend/server.py` (in-memory storage)
- **Production**: Docker Compose with all services + PostgreSQL + MCP Server

## User Personas
1. **Volunteer** - Chat interface for onboarding
2. **Ops/Coordinator** - Pipeline dashboard
3. **Tech Admin** - Debug console

## What's Been Implemented

### Phase 1: Service Structure ✅
- [x] serve-orchestrator - FastAPI, own main.py, Dockerfile
- [x] serve-onboarding-agent-service - FastAPI, own main.py, Dockerfile
- [x] serve-data-service - FastAPI, own main.py, Dockerfile (was serve-agentic-mcp-service)
- [x] serve-ai-ui - React, own Dockerfile
- [x] Docker Compose with Postgres persistent volume
- [x] Clean separation - no combined backend

### Phase 2: Onboarding Vertical Slice ✅
- [x] Orchestrator: session routing, agent handoff
- [x] Onboarding Agent: LLM integration, state machine
- [x] Data Service: 15+ capability endpoints
- [x] Database: sessions, profiles, messages, events, telemetry

### Phase 3: Orchestrator Architectural Improvements ✅ (Dec 2025)
- [x] **Structured Interaction Contracts** (`/app/serve-orchestrator/app/schemas/contracts.py`)
- [x] **AgentRouter** (`/app/serve-orchestrator/app/service/agent_router.py`)
- [x] **WorkflowValidator** (`/app/serve-orchestrator/app/service/workflow_validator.py`)
- [x] **Enhanced Structured Logging**

### Phase 4: Postgres Integration ✅
- [x] Data Service uses async SQLAlchemy with PostgreSQL
- [x] All entities defined with proper relationships
- [x] Preview environment uses in-memory fallback (by design)
- [x] Docker Compose configures production Postgres

### Phase 5: Onboarding Agent Autonomy ✅ (Dec 2025)
- [x] **eVidyaloka-Aligned Tone** - Warm, volunteer-oriented communication
- [x] **Dynamic Question Selection** - Priority-based field collection
- [x] **Robust Profile Extraction** - Fixed name extraction bug, added skill synonyms
- [x] **Autonomous State Transitions** - Data-driven progression

### Phase 6: Conversation Memory Summarization ✅ (Dec 2025)
- [x] **Memory Summarizer Service** (`/app/serve-onboarding-agent-service/app/service/memory_service.py`)
  - LLM-powered summarization of conversation history
  - Key fact extraction from conversations
  - Configurable summarization threshold (every 6 messages)
- [x] **Memory Context in Prompts**
  - Returning volunteer context generation
  - Natural integration without explicit memory mention
- [x] **Memory Capabilities** (HTTP endpoints, migrating to MCP)
  - `save-memory-summary` - Store conversation summaries
  - `get-memory-summary` - Retrieve session memory
- [x] **Automatic Summary Triggers**
  - Periodic summarization during conversation
  - Summary on pause for context preservation
  - Final summary before handoff with key facts

### Phase 8: Real MCP Server (Model Context Protocol) ✅ (Dec 2025)
- [x] **MCP Server Foundation** (`/app/serve-mcp-server/`)
  - Uses official Python MCP SDK (`pip install mcp`)
  - Protocol-compliant tool definitions with typed schemas
  - FastMCP decorator-based tool registration
- [x] **13 MCP Tools Implemented**
  - Session: `start_session`, `get_session`, `resume_session`, `advance_session_state`
  - Profile: `get_missing_fields`, `save_volunteer_fields`, `get_volunteer_profile`, `evaluate_readiness`
  - Messages: `save_message`, `get_conversation`
  - Memory: `save_memory_summary`, `get_memory_summary`
  - Telemetry: `log_event`
- [x] **Service Layer Architecture**
  - Business logic in `services/` (reusable)
  - MCP tools wrap services with typed interfaces
  - In-memory storage (ready for Postgres connection)

### Frontend ✅
- [x] Volunteer-first landing page (eVidyaloka branding)
- [x] Role selector moved to /internal route
- [x] Volunteer chat interface (no system terminology)
- [x] Ops dashboard, Admin console (internal only)
- [x] Journey progress tracker (eVidyaloka terminology)
- [x] Profile display
- [x] Mission-driven design

### Phase 7: Volunteer-First UI Flow ✅ (Dec 2025)
- [x] **Volunteer Landing Page** (`/app/frontend/src/views/VolunteerLanding.jsx`)
  - Hero section with rural India classroom imagery
  - "Help a child learn, change a life" messaging
  - "Start your volunteer journey" CTA
  - Impact stats (children, volunteers, villages)
  - How it works section
  - Testimonial quote
- [x] **Internal Staff Portal** (`/internal` route)
  - Role selector for Volunteer Preview, Ops, Tech Admin
  - No volunteer-facing terminology
  - "eVidyaloka Staff Portal" branding
- [x] **Updated Volunteer Chat**
  - eVidyaloka branding throughout
  - Back button to landing page
  - Warm amber color scheme
  - "Welcome Aboard!" final stage
- [x] **Terminology Cleanup**
  - Removed: SERVE AI, MCP, orchestration, platform roles
  - Added: eVidyaloka mission-aligned messaging

## Key Files Reference

### Frontend (Volunteer-Facing)
- `/app/frontend/src/views/VolunteerLanding.jsx` - Landing page
- `/app/frontend/src/views/VolunteerView.jsx` - Chat interface
- `/app/frontend/src/components/serve/JourneyProgress.jsx` - Progress tracker

### Frontend (Internal Staff)
- `/app/frontend/src/views/RoleSelector.jsx` - Internal role selector
- `/app/frontend/src/views/OpsView.jsx` - Operations dashboard
- `/app/frontend/src/views/AdminView.jsx` - Tech admin console

### Orchestrator Service
- `/app/serve-orchestrator/app/schemas/contracts.py` - Interaction contracts
- `/app/serve-orchestrator/app/service/agent_router.py` - AgentRouter
- `/app/serve-orchestrator/app/service/workflow_validator.py` - WorkflowValidator

### Onboarding Agent Service
- `/app/serve-onboarding-agent-service/app/service/llm_adapter.py` - eVidyaloka prompts
- `/app/serve-onboarding-agent-service/app/service/onboarding_logic.py` - Agent logic
- `/app/serve-onboarding-agent-service/app/service/memory_service.py` - Memory summarization

### MCP Service (Database Owner)
- `/app/serve-agentic-mcp-service/app/db/database.py` - Postgres config
- `/app/serve-agentic-mcp-service/app/models/entities.py` - SQLAlchemy models (includes MemorySummary)
- `/app/serve-agentic-mcp-service/app/service/onboarding_capabilities.py` - Business logic + memory ops

### Preview Environment
- `/app/backend/server.py` - Monolithic server with all features (in-memory)

## Prioritized Backlog

### P0 - Next
- [ ] Deploy with `docker-compose up -d` to verify Postgres integration
- [ ] Selection Agent service implementation

### P1 - High
- [ ] WhatsApp channel adapter
- [ ] Enhanced NLP extraction with LLM
- [ ] Firebase authentication

### P2 - Medium
- [ ] Engagement Agent
- [ ] Need Agent
- [ ] Volunteer dashboard

## API Endpoints

### Memory Summary Endpoints (NEW)
- `POST /api/mcp/capabilities/onboarding/save-memory-summary`
- `POST /api/mcp/capabilities/onboarding/get-memory-summary`
- `GET /api/mcp/capabilities/onboarding/memory/{session_id}`
- `GET /api/mcp/capabilities/onboarding/volunteer-memory/{volunteer_id}`

### Orchestrator
- `POST /api/orchestrator/interact` - Main entry point
- `GET /api/orchestrator/session/{id}` - Get session
- `GET /api/orchestrator/sessions` - List sessions

### Onboarding Agent
- `POST /api/agents/onboarding/turn` - Process agent turn

### MCP Capabilities
- `POST /api/mcp/capabilities/onboarding/start-session`
- `POST /api/mcp/capabilities/onboarding/resume-context`
- And 15+ more capability endpoints

## Database Schema (PostgreSQL)
- **sessions**: id, channel, persona, workflow, active_agent, status, stage...
- **volunteer_profiles**: id, session_id, full_name, email, skills, availability...
- **conversation_messages**: id, session_id, role, content, agent...
- **memory_summaries**: id, session_id, volunteer_id, summary_text, key_facts, created_at
- **handoff_events**: id, session_id, from_agent, to_agent, payload...
- **telemetry_events**: id, session_id, event_type, agent, data...
