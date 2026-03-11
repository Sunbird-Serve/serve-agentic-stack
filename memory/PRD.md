# SERVE AI - Product Requirements Document

## Original Problem Statement
Build the foundational scaffold for a SERVE AI multi-agent volunteer management platform - a Digital Public Good (DPG) aligned with DPGA.

## Architecture
```
serve-ai-ui (React) → serve-orchestrator (FastAPI) → serve-agents → serve-agentic-mcp-service → PostgreSQL
```

## User Personas
1. **Volunteer** - Interacts via chat interface for onboarding
2. **Ops/Coordinator** - Monitors volunteer pipeline via Kanban dashboard  
3. **Tech Admin** - Debugs sessions, views telemetry, MCP logs

## Core Requirements (Static)
- Multi-service architecture with clear boundaries
- Channel-agnostic orchestration (Web UI, WhatsApp ready)
- MCP capability server owns database/persistence
- LLM-powered onboarding agent (Claude Sonnet 4.5)
- Strongly typed contracts between services
- Docker Compose for local development

## What's Been Implemented (Jan 2026)
### Backend Services
- [x] serve-orchestrator - Central coordination layer
- [x] serve-onboarding-agent-service - Autonomous onboarding agent with LLM
- [x] serve-agentic-mcp-service - MCP capability server with in-memory fallback
- [x] Shared contracts and enums
- [x] SQLAlchemy models for Postgres (with in-memory fallback)
- [x] 12 MCP capability endpoints for onboarding

### Frontend (React)
- [x] Role selector landing page
- [x] Volunteer chat view with journey progress
- [x] Ops/Coordinator pipeline dashboard (Kanban)
- [x] Tech Admin debug console
- [x] DPGA-aligned design system (light mode)
- [x] Custom SERVE AI logo

### Integration
- [x] Claude Sonnet 4.5 via emergentintegrations
- [x] Configurable LLM adapter layer (swap providers)
- [x] Docker Compose setup
- [x] Health endpoints for all services

## Prioritized Backlog

### P0 - Critical
- [ ] PostgreSQL persistence (Docker volume setup)
- [ ] Production deployment configuration

### P1 - High
- [ ] Selection Agent service
- [ ] WhatsApp channel adapter
- [ ] Volunteer profile completion flow

### P2 - Medium  
- [ ] Engagement Agent service
- [ ] Need Agent service
- [ ] Coordinator dashboard features

### P3 - Future
- [ ] Fulfillment Agent
- [ ] Delivery Assistant
- [ ] Analytics dashboard

## Next Tasks
1. Set up PostgreSQL in production
2. Implement Selection Agent following same pattern
3. Add WhatsApp integration via Twilio
4. Complete volunteer profile fields validation
