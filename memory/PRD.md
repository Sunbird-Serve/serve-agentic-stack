# SERVE AI - Product Requirements Document

## Original Problem Statement
Build the foundational scaffold for a SERVE AI multi-agent volunteer management platform with clean service boundaries - a Digital Public Good aligned with DPGA.

## Architecture (Final - Jan 2026)

```
/app/
├── serve-ai-ui/                    # React Frontend (Port 3000)
├── serve-orchestrator/             # Coordination Layer (Port 8001)
├── serve-onboarding-agent-service/ # Onboarding Agent (Port 8002)
├── serve-agentic-mcp-service/      # MCP + Database (Port 8003)
├── docker-compose.yml              # All services + Postgres
└── README.md
```

### Service Communication
- UI → Orchestrator (HTTP)
- Orchestrator → Agent Services (HTTP)
- Agent Services → MCP Service (HTTP)
- MCP Service → PostgreSQL (Direct)

### Runtime
- **Preview**: Monolithic `/app/backend/server.py` (in-memory storage)
- **Production**: Docker Compose with all 5 services + PostgreSQL

## User Personas
1. **Volunteer** - Chat interface for onboarding
2. **Ops/Coordinator** - Pipeline dashboard
3. **Tech Admin** - Debug console

## What's Been Implemented

### Phase 1: Service Structure ✅
- [x] serve-orchestrator - FastAPI, own main.py, Dockerfile
- [x] serve-onboarding-agent-service - FastAPI, own main.py, Dockerfile
- [x] serve-agentic-mcp-service - FastAPI, own main.py, Dockerfile
- [x] serve-ai-ui - React, own Dockerfile
- [x] Docker Compose with Postgres persistent volume
- [x] Clean separation - no combined backend

### Phase 2: Onboarding Vertical Slice ✅
- [x] Orchestrator: session routing, agent handoff
- [x] Onboarding Agent: LLM integration, state machine
- [x] MCP Service: 15+ capability endpoints
- [x] Database: sessions, profiles, messages, events, telemetry

### Phase 3: Orchestrator Architectural Improvements ✅ (Dec 2025)
- [x] **Structured Interaction Contracts** (`/app/serve-orchestrator/app/schemas/contracts.py`)
  - RoutingDecision, TransitionValidation models
  - AgentInvocationContext, AgentInvocationResult
  - WorkflowDefinition, WorkflowStageDefinition
  - SessionContext, OrchestrationEvent
- [x] **AgentRouter** (`/app/serve-orchestrator/app/service/agent_router.py`)
  - AgentRegistry for service discovery
  - Intelligent routing based on workflow and stage
  - Fallback handling when agents unavailable
  - Structured routing event logging
- [x] **WorkflowValidator** (`/app/serve-orchestrator/app/service/workflow_validator.py`)
  - Complete NEW_VOLUNTEER_ONBOARDING_WORKFLOW definition
  - Stage transition validation with field requirements
  - Completion percentage calculation
  - Validation event logging
- [x] **Enhanced Structured Logging**
  - OrchestrationEventType enum
  - Event-driven logging for all orchestration activities
  - Routing decisions, state transitions, handoffs tracked

### Phase 4: Postgres Integration ✅
- [x] MCP Service uses async SQLAlchemy with PostgreSQL
- [x] All entities defined with proper relationships
- [x] Preview environment uses in-memory fallback (by design)
- [x] Docker Compose configures production Postgres

### Phase 5: Onboarding Agent Autonomy ✅ (Dec 2025)
- [x] **eVidyaloka-Aligned Tone**
  - Warm, volunteer-oriented communication
  - Mission-connected messaging without being preachy
  - Simple language, no technical jargon
  - Never mentions: workflow, orchestrator, MCP, agent, system
- [x] **Dynamic Question Selection**
  - build_state_prompt() generates contextual prompts
  - Priority-based field collection (name → email → skills → availability)
  - Acknowledges confirmed fields, focuses on missing ones
- [x] **Robust Profile Extraction**
  - Enhanced ProfileExtractor class with regex patterns
  - Name extraction with noise removal ("Sarah And I" → "Sarah")
  - Skill keyword synonyms (math → mathematics, code → programming)
  - Phone number pattern matching (multiple formats)
  - Location extraction from various phrases
  - Availability detection (hours/week, weekdays, weekends)
- [x] **Autonomous State Transitions**
  - Data-driven progression (not just keyword matching)
  - Pause/resume handling
  - Validation before each transition
- [x] **Readiness Evaluation**
  - evaluate_readiness() checks all required fields
  - Handoff preparation with complete profile

### Frontend ✅
- [x] Role selector, Volunteer chat, Ops dashboard, Admin console
- [x] Journey progress tracker
- [x] Profile display
- [x] DPGA-aligned design

## Key Files Reference

### Orchestrator Service
- `/app/serve-orchestrator/app/schemas/contracts.py` - Interaction contracts
- `/app/serve-orchestrator/app/service/agent_router.py` - AgentRouter
- `/app/serve-orchestrator/app/service/workflow_validator.py` - WorkflowValidator
- `/app/serve-orchestrator/app/service/orchestration.py` - Main orchestration logic

### Onboarding Agent Service
- `/app/serve-onboarding-agent-service/app/service/llm_adapter.py` - eVidyaloka prompts
- `/app/serve-onboarding-agent-service/app/service/onboarding_logic.py` - Agent logic

### MCP Service (Database Owner)
- `/app/serve-agentic-mcp-service/app/db/database.py` - Postgres config
- `/app/serve-agentic-mcp-service/app/models/entities.py` - SQLAlchemy models
- `/app/serve-agentic-mcp-service/app/service/onboarding_capabilities.py` - Business logic

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

### Orchestrator
- `POST /api/orchestrator/interact` - Main entry point
- `GET /api/orchestrator/session/{id}` - Get session
- `GET /api/orchestrator/sessions` - List sessions

### Onboarding Agent
- `POST /api/agents/onboarding/turn` - Process agent turn

### MCP Capabilities
- `POST /api/mcp/capabilities/onboarding/start-session`
- `POST /api/mcp/capabilities/onboarding/resume-context`
- `POST /api/mcp/capabilities/onboarding/advance-state`
- `POST /api/mcp/capabilities/onboarding/get-missing-fields`
- `POST /api/mcp/capabilities/onboarding/save-confirmed-fields`
- `POST /api/mcp/capabilities/onboarding/save-message`
- And 10+ more capability endpoints

## Database Schema (PostgreSQL)
- **sessions**: id, channel, persona, workflow, active_agent, status, stage...
- **session_events**: id, session_id, event_type, from_state, to_state...
- **volunteer_profiles**: id, session_id, full_name, email, skills, availability...
- **conversation_messages**: id, session_id, role, content, agent...
- **memory_summaries**: id, session_id, summary_text, key_facts...
- **handoff_events**: id, session_id, from_agent, to_agent, payload...
- **telemetry_events**: id, session_id, event_type, agent, data...
