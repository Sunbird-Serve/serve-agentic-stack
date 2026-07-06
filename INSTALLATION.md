# SERVE AI Platform — Installation Guide

## Prerequisites

- Docker & Docker Compose (v2.x+)
- Git
- A valid Anthropic API key (for LLM features)

## Quick Start

### 1. Clone the repository

```bash
git clone <repo-url>
cd serve-ai
```

### 2. Configure environment variables

Copy the example env file and fill in the required values:

```bash
cp .env.example .env
```

Edit `.env` and set:

```env
# Required — LLM API key (Anthropic Claude)
EMERGENT_LLM_KEY=sk-ant-api03-your-key-here

# Required — Keycloak Configuration
# Local: http://localhost:8080
# Sandbox: https://auth.serve-v1.evean.net
# Production: https://auth.up.serve.net.in
KEYCLOAK_URL=http://localhost:8080
KEYCLOAK_REALM=sunbird-serve

# Optional — WhatsApp Cloud API (for WhatsApp channel)
WHATSAPP_TOKEN=your-whatsapp-token
WHATSAPP_PHONE_NUMBER_ID=your-phone-number-id
WHATSAPP_APP_SECRET=your-app-secret

# Optional — Teaching language for selection agent (default: English)
TEACHING_LANGUAGE=English
```

### Keycloak Setup

The platform uses an existing Keycloak instance for authentication. The `serve-ui` public PKCE client must be configured:

1. Open Keycloak Admin Console for your realm (`sunbird-serve`)
2. Navigate to Clients → `serve-ui`
3. Add the agentic UI URL to **Valid Redirect URIs**: `http://localhost:3000/*`
4. Add to **Web Origins**: `http://localhost:3000`

All users must exist in Keycloak before they can access the platform.

### 3. Start all services

```bash
docker-compose up --build
```

This starts:
| Service | Port | Description |
|---------|------|-------------|
| serve-ai-ui | 3000 | React frontend |
| serve-orchestrator | 8001 | Central coordination layer |
| serve-onboarding-agent-service | 8002 | Volunteer onboarding |
| serve-mcp-server | 8004 | MCP server + PostgreSQL interface |
| serve-need-agent-service | 8005 | Need coordination |
| serve-engagement-agent-service | 8006 | Volunteer engagement |
| serve-fulfillment-agent-service | 8007 | Volunteer-to-need matching |
| serve-selection-agent-service | 8009 | Post-onboarding evaluation |
| postgres | 5433 | PostgreSQL database |

### 4. Access the application

- **Volunteer UI**: http://localhost:3000
- **Internal Staff Portal**: http://localhost:3000/internal
- **Orchestrator Health**: http://localhost:8001/api/health
- **MCP Server Health**: http://localhost:8004/api/health

### 5. Verify all services are healthy

```bash
curl http://localhost:8001/api/health
curl http://localhost:8002/api/health
curl http://localhost:8004/api/health
curl http://localhost:8005/api/health
curl http://localhost:8006/api/health
curl http://localhost:8007/api/health
curl http://localhost:8009/api/health
```

All should return `{"status": "healthy"}`.

## Architecture Overview

```
Frontend (3000) → Orchestrator (8001) → Agents → MCP Server (8004) → PostgreSQL
                                                                    → Serve Registry (external)
```

The orchestrator routes requests to the appropriate agent based on persona detection:
- New volunteers → Onboarding → Selection → Engagement → Fulfillment
- Returning volunteers → Engagement → Fulfillment
- Recommended volunteers → Engagement (recommended handler) → Fulfillment
- Need coordinators → Need Agent

## Service-Specific Configuration

### Onboarding Agent (Port 8002)

Videos for orientation are served from `serve-onboarding-agent-service/media/`:
- `welcome.mp4` — Coordinator welcome video
- `serve_class_intro.mp4` — Classroom demo video

### MCP Server (Port 8004)

Connects to external Serve Registry at `https://serve-v1.evean.net`. Override with:
```env
SERVE_BASE_URL=https://serve-v1.evean.net
```

Database is auto-initialized on first start. Migrations run automatically.

### Selection Agent (Port 8009)

Configure teaching language:
```env
TEACHING_LANGUAGE=Hindi
```

## Development

### Rebuilding a single service

```bash
docker-compose up --build serve-onboarding-agent-service
```

### Viewing logs for a specific service

```bash
docker-compose logs -f serve-orchestrator
docker-compose logs -f serve-onboarding-agent-service
docker-compose logs -f serve-mcp-server
```

### Accessing the database

```bash
docker exec -it serve-postgres psql -U serve -d serve_db
```

### Useful queries

Fetch all sessions:
```sql
SELECT id, actor_id, workflow, active_agent, stage, status, created_at FROM sessions ORDER BY created_at DESC LIMIT 20;
```

Fetch conversations for a phone number:
```sql
SELECT s.id, s.stage, cm.role, cm.content, cm.created_at
FROM sessions s
JOIN conversation_messages cm ON cm.session_id = s.id
WHERE s.actor_id LIKE '%7760131282'
ORDER BY cm.created_at ASC;
```

### Resetting the database

```bash
docker-compose down -v
docker-compose up --build
```

This removes the PostgreSQL volume and starts fresh.

## WhatsApp Integration

1. Set up a Meta Business App with WhatsApp Cloud API
2. Configure webhook URL: `https://your-domain/api/whatsapp/webhook`
3. Set verify token: `serve_verify_token` (or override with `WHATSAPP_VERIFY_TOKEN`)
4. Add the env vars to `.env`

Videos are sent as native WhatsApp media messages (uploaded via Graph API).

## Troubleshooting

**500 errors on orchestrator**: Check MCP server logs — usually a DB or registry connection issue.

**LLM not responding**: Verify `EMERGENT_LLM_KEY` is set and valid. Check agent logs for API errors.

**Registration failing (400)**: Check MCP server logs for the exact payload being sent to the Serve Registry.

**Selection agent asking wrong language**: Set `TEACHING_LANGUAGE` env var in docker-compose.

**Videos not playing in UI**: Ensure the onboarding agent is running and `/media` endpoint is accessible at `http://localhost:8002/media/serve_class_intro.mp4`.
