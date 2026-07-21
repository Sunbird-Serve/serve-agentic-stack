# SERVE Delivery Agent Service

Owns the **post-handshake delivery journey**: once a volunteer is matched and
approved for a need, this agent activates them and runs daily session operations
until the programme completes, pauses, or escalates.

- **Port:** 8010
- **Agent:** `delivery_assistant`
- **Workflow:** `delivery_support`

## Two modes

1. **Activation** — introduce the assignment, confirm the volunteer's
   acknowledgement and first-session readiness, then complete activation.
2. **Daily operations** — for every scheduled session: send policy-driven
   reminders, run a completion check, capture the verified outcome, log blockers,
   capture reschedule requests, and escalate stalled deliveries.

## Core principle

**Reminders and completion checks are deterministic policy, never LLM decisions.**
`policy_engine.py` (pure functions) decides *what* fires and *when*;
`reminder_engine.py` dispatches it; the LLM (`llm_adapter.py`) only converses and
persists confirmed facts through tool calls.

## Architecture

| File | Role |
|---|---|
| `app/service/policy_engine.py` | Pure policy: reminder windows, suppression, one-follow-up rule, escalation thresholds, stage-transition table, reminder templates |
| `app/service/reminder_engine.py` | Deterministic `tick()` — send due reminders, mark unverified, escalate |
| `app/service/delivery_logic.py` | Turn brain: resolve context, dispatch mode, run LLM loop, finalize stage |
| `app/service/llm_adapter.py` | LiteLLM tool-loop (model-agnostic, retry + honest fallback) |
| `app/clients/domain_client.py` | MCP SSE client → `delivery_*` tools on serve-mcp-server |

Delivery data (deliveries, scheduled sessions, reminders, blockers, reschedule
requests) is owned by the MCP server (`serve-mcp-server/services/delivery_service.py`).

## Endpoints

- `POST /api/turn` — conversational turn (orchestrator contract).
- `GET  /api/health` — health probe.
- `POST /api/reminders/tick` — run one reminder pass. Body (optional):
  `{"delivery_id": "...", "now": "2026-07-20T08:00:00"}`.
- `POST /api/debug/seed` — (dev, needs `DEBUG_ENDPOINTS=true`) seed a demo
  delivery + session; returns `session_id` / `delivery_id`.
- `GET  /api/debug/state/{session_id}` — (dev) inspect context + recent events.

## Key env vars

| Var | Default | Meaning |
|---|---|---|
| `REMINDER_TICK_SECONDS` | 300 | Background reminder loop interval. `0` disables it (tests drive `/tick`). |
| `DELIVERY_PRE_SESSION_MINUTES` | 45 | Pre-session reminder window before start. |
| `DELIVERY_FOLLOWUP_DELAY_MINUTES` | 60 | Delay before the single follow-up nudge. |
| `DELIVERY_UNVERIFIED_GRACE_MINUTES` | 60 | Grace after follow-up before marking unverified. |
| `DELIVERY_ESCALATION_MISS_THRESHOLD` | 2 | Consecutive misses → escalate. |
| `DELIVERY_ESCALATION_UNVERIFIED_THRESHOLD` | 2 | Consecutive unverified → escalate. |
| `DEBUG_ENDPOINTS` | false | Enable `/api/debug/*`. |
| `LOG_LEVEL` | INFO | `DEBUG` dumps truncated LLM prompts. |

## Tests

```bash
pip install -r requirements.txt   # includes pytest, pytest-asyncio
python -m pytest tests -v
```

- `test_policy_engine.py` — reminder windows, suppression, follow-up limit,
  unverified rule, escalation thresholds, transition table (pure, no I/O).
- `test_delivery_logic.py` — mode dispatch, missing-context edge, terminal guards
  (MCP + LLM mocked).
- `test_api.py` — health + reminder-tick idempotency (two ticks → one send).
