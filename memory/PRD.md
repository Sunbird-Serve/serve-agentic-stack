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
- **Primary**: Docker Compose with all 5 services
- **Database**: PostgreSQL with persistent volume

## User Personas
1. **Volunteer** - Chat interface for onboarding
2. **Ops/Coordinator** - Pipeline dashboard
3. **Tech Admin** - Debug console

## What's Been Implemented

### Service Structure ✅
- [x] serve-orchestrator - FastAPI, own main.py, Dockerfile
- [x] serve-onboarding-agent-service - FastAPI, own main.py, Dockerfile
- [x] serve-agentic-mcp-service - FastAPI, own main.py, Dockerfile
- [x] serve-ai-ui - React, own Dockerfile
- [x] Docker Compose with Postgres persistent volume
- [x] Clean separation - no combined backend

### Onboarding Vertical Slice ✅
- [x] Orchestrator: session routing, agent handoff
- [x] Onboarding Agent: LLM integration, state machine
- [x] MCP Service: 15+ capability endpoints
- [x] Database: sessions, profiles, messages, events, telemetry

### Frontend ✅
- [x] Role selector, Volunteer chat, Ops dashboard, Admin console
- [x] DPGA-aligned design

## Prioritized Backlog

### P0 - Next
- [ ] Deploy with `docker-compose up -d`
- [ ] Selection Agent service

### P1 - High
- [ ] WhatsApp channel adapter
- [ ] Enhanced NLP extraction

### P2 - Medium
- [ ] Engagement Agent
- [ ] Need Agent

## Next Tasks
1. `docker-compose up -d` to run all services
2. Verify Postgres persistence
3. Add Selection Agent following same pattern
