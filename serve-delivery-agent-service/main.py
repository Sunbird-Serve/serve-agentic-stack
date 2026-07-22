"""
SERVE Delivery Agent Service

Owns the post-handshake delivery journey: activation + daily session operations.

Port: 8010
Workflow: delivery_support
Agent: delivery_assistant

Endpoints:
  POST /api/turn              — conversational turn (orchestrator contract)
  GET  /api/health            — health probe
  POST /api/reminders/tick    — run one deterministic reminder pass
  POST /api/debug/seed        — (dev) seed a demo delivery + session for testing
  GET  /api/debug/state/{sid} — (dev) inspect delivery context + recent events
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware

from app.schemas.delivery_schemas import DeliveryAgentTurnRequest, ActivationStage
from app.service.delivery_logic import delivery_agent_service
from app.service.reminder_engine import reminder_engine
from app.clients.domain_client import domain_client, _call_mcp_tool
from app.auth import get_optional_user, UserClaims

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("delivery.main")

# Background reminder loop interval (seconds). 0 disables the loop entirely so
# tests / manual runs drive reminders via POST /api/reminders/tick.
_TICK_SECONDS = int(os.environ.get("REMINDER_TICK_SECONDS", "300"))
_DEBUG_ENDPOINTS = os.environ.get("DEBUG_ENDPOINTS", "false").lower() == "true"

# Small in-process telemetry ring buffer for the debug endpoint
_EVENTS: list = []
_EVENTS_MAX = 200


def _record_event(kind: str, detail: dict):
    _EVENTS.append({"ts": datetime.utcnow().isoformat(), "kind": kind, **detail})
    if len(_EVENTS) > _EVENTS_MAX:
        del _EVENTS[0]


async def _reminder_loop():
    logger.info(f"Reminder loop starting — interval={_TICK_SECONDS}s")
    while True:
        try:
            summary = await reminder_engine.tick()
            if summary.get("sent") or summary.get("unverified"):
                _record_event("reminder_tick", {"sent": len(summary.get("sent", [])),
                                                "unverified": len(summary.get("unverified", []))})
        except Exception as e:
            logger.warning(f"Reminder loop tick failed: {e}")
        await asyncio.sleep(_TICK_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting SERVE Delivery Agent Service...")
    task = None
    if _TICK_SECONDS > 0:
        task = asyncio.create_task(_reminder_loop())
    else:
        logger.info("Reminder loop disabled (REMINDER_TICK_SECONDS=0) — use POST /api/reminders/tick")
    yield
    if task:
        task.cancel()
    logger.info("Shutting down SERVE Delivery Agent Service...")


app = FastAPI(
    title="SERVE Delivery Agent Service",
    description="Post-handshake delivery assistant (activation + daily operations)",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/turn")
async def process_turn(request: Request, user: UserClaims = Depends(get_optional_user)):
    """Process a delivery conversation turn. Requires (optional) JWT forwarded by
    the orchestrator."""
    try:
        body = await request.json()
        req = DeliveryAgentTurnRequest(**body)
        response = await delivery_agent_service.process_turn(req)
        _record_event("turn", {"session_id": str(req.session_id), "state": response.state})
        return response.model_dump(mode="json")
    except Exception as e:
        logger.error(f"Error processing delivery turn: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health():
    return {"service": "serve-delivery-agent-service", "status": "healthy", "version": "1.0.0"}


@app.post("/api/reminders/tick")
async def reminders_tick(request: Request):
    """Run one reminder pass. Optional JSON body: {delivery_id, now (ISO)}."""
    try:
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        now = datetime.fromisoformat(body["now"]) if body.get("now") else None
        summary = await reminder_engine.tick(now=now, delivery_id=body.get("delivery_id"))
        _record_event("reminder_tick", {"sent": len(summary.get("sent", [])),
                                        "unverified": len(summary.get("unverified", []))})
        return summary
    except Exception as e:
        logger.error(f"Reminder tick failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Debug endpoints (dev only) ────────────────────────────────────────────────

@app.post("/api/debug/seed")
async def debug_seed(request: Request):
    """Seed a demo delivery + one scheduled session for manual testing.

    Body (all optional): {volunteer_name, subject, days_from_now (int, default 0),
    start_time ("HH:MM"), past (bool → schedule a session already ended)}.
    Returns session_id + delivery_id.
    """
    if not _DEBUG_ENDPOINTS:
        raise HTTPException(status_code=404, detail="Not found")
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    # 1. Create a conversation session (system persona)
    sess = await _call_mcp_tool("start_session", {
        "channel": "api", "persona": "system", "actor_id": "delivery-demo",
    })
    session_id = sess.get("session_id")
    if not session_id:
        raise HTTPException(status_code=500, detail=f"start_session failed: {sess}")

    # 2. Start activation (creates the delivery, linked to the session).
    # Each seed call gets its OWN volunteer/need id by default — reusing a fixed
    # id across repeated seed calls piles multiple open scheduled sessions onto
    # one delivery, which makes /api/turn ambiguous about which session a reply
    # refers to. Pass "reuse_delivery": true explicitly to test the resume path.
    demo_suffix = session_id[:8] if not body.get("reuse_delivery") else "shared"
    act = await domain_client.start_activation(
        session_id=session_id,
        volunteer_id=f"demo-volunteer-{demo_suffix}",
        volunteer_name=body.get("volunteer_name", "Asha Rao"),
        need_id=f"demo-need-{demo_suffix}",
        entity_id="demo-school-001",
        programme="eVidyaloka Online Teaching",
        expected_sessions=int(body.get("expected_sessions", 3)),
    )
    delivery = act.get("delivery", {})
    delivery_id = delivery.get("id")
    if not delivery_id:
        raise HTTPException(status_code=500, detail=f"start_activation failed: {act}")

    # 3. Create a scheduled session
    if body.get("past"):
        d = datetime.now() - timedelta(hours=2)
        sched_date = d.date().isoformat()
        start_time = (d - timedelta(minutes=60)).strftime("%H:%M")
        end_time = d.strftime("%H:%M")
    else:
        days = int(body.get("days_from_now", 0))
        sched_date = (date.today() + timedelta(days=days)).isoformat()
        start_time = body.get("start_time", (datetime.now() + timedelta(minutes=30)).strftime("%H:%M"))
        end_time = body.get("end_time", (datetime.now() + timedelta(minutes=90)).strftime("%H:%M"))

    sess_row = await domain_client.create_scheduled_session(
        delivery_id=delivery_id, session_number=1, scheduled_date=sched_date,
        start_time=start_time, end_time=end_time, subject=body.get("subject", "Mathematics"),
        meeting_link="https://meet.evidyaloka.org/demo", delivery_mode="online",
    )

    # 4. Point the session at the delivery agent
    await domain_client.advance_state(session_id, ActivationStage.ACTIVATION_STARTED.value,
                                      active_agent="delivery_assistant", workflow="delivery_support")

    _record_event("debug_seed", {"session_id": session_id, "delivery_id": delivery_id})
    return {
        "status": "success", "session_id": session_id, "delivery_id": delivery_id,
        "scheduled_session": sess_row.get("session"),
        "hint": "POST /api/turn with this session_id to start activation; "
                "POST /api/reminders/tick to fire reminders.",
    }


@app.get("/api/debug/state/{session_id}")
async def debug_state(session_id: str):
    """Inspect the delivery context for a session + recent in-process events."""
    if not _DEBUG_ENDPOINTS:
        raise HTTPException(status_code=404, detail="Not found")
    ctx = await domain_client.get_context(session_id=session_id)
    events = [e for e in _EVENTS if e.get("session_id") == session_id] or _EVENTS[-25:]
    return {"context": ctx, "recent_events": events}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8010))
    uvicorn.run(app, host="0.0.0.0", port=port)
