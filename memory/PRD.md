# SERVE AI - Product Requirements Document

## Original Problem Statement
Build the foundational scaffold for a SERVE AI multi-agent volunteer management platform with clean service boundaries - a Digital Public Good aligned with DPGA.

## Architecture (Refactored Jan 2026)
```
/app/
├── serve-ai-ui/                    # React Frontend (Port 3000)
├── serve-orchestrator/             # Coordination Layer (Port 8001)
├── serve-onboarding-agent-service/ # Onboarding Agent (Port 8002)
├── serve-agentic-mcp-service/      # MCP + Database (Port 8003)
└── docker-compose.yml              # All services + Postgres
```

### Service Communication
- UI → Orchestrator (HTTP)
- Orchestrator → Agent Services (HTTP)
- Agent Services → MCP Service (HTTP)
- MCP Service → PostgreSQL (Direct)

## User Personas
1. **Volunteer** - Chat interface for onboarding
2. **Ops/Coordinator** - Pipeline dashboard
3. **Tech Admin** - Debug console

## What's Been Implemented (Jan 2026)

### Service Structure ✅
- [x] serve-orchestrator - Own folder, FastAPI app, main.py, Dockerfile
- [x] serve-onboarding-agent-service - Own folder, FastAPI app, main.py, Dockerfile
- [x] serve-agentic-mcp-service - Own folder, FastAPI app, main.py, Dockerfile
- [x] serve-ai-ui - Own folder, React app, Dockerfile
- [x] Docker Compose with Postgres persistent volume

### Backend ✅
- [x] Orchestrator: session resolution, agent routing, handoff management
- [x] Onboarding Agent: LLM integration (Claude Sonnet 4.5), state machine
- [x] MCP Service: 15+ capability endpoints, SQLAlchemy models
- [x] PostgreSQL schema: sessions, profiles, messages, events, telemetry

### Frontend ✅
- [x] Role selector landing page
- [x] Volunteer chat view with journey progress
- [x] Ops pipeline dashboard (Kanban)
- [x] Tech Admin debug console
- [x] DPGA-aligned design system

### Database Entities ✅
- sessions, session_events, volunteer_profiles
- conversation_messages, memory_summaries
- handoff_events, telemetry_events

## Prioritized Backlog

### P0 - Next Sprint
- [ ] Deploy with Docker Compose + Postgres
- [ ] Selection Agent service

### P1 - High
- [ ] WhatsApp channel adapter
- [ ] Real-time WebSocket notifications
- [ ] Enhanced profile extraction (NLP)

### P2 - Medium
- [ ] Engagement Agent service
- [ ] Need Agent service
- [ ] Coordinator features

### P3 - Future
- [ ] Fulfillment Agent
- [ ] Delivery Assistant
- [ ] Analytics dashboard

## Next Tasks
1. Deploy with `docker-compose up -d`
2. Verify Postgres persistence
3. Implement Selection Agent following same pattern
4. Add WhatsApp integration
