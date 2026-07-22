"""
SERVE Orchestrator Service - Main Entry Point
Central coordination layer for SERVE AI
"""
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, PlainTextResponse
import os
import logging
import httpx
import hmac
import hashlib
import json
from datetime import datetime

import asyncio
from app.api import orchestrator_router
from app.schemas import HealthResponse, InteractionRequest, ChannelType, PersonaType
from app.service.agent_router import agent_router
from app.service import orchestration_service

MCP_SERVICE_URL = os.environ.get("MCP_SERVICE_URL") or os.environ.get("MCP_SERVER_URL", "http://serve-mcp-server:8004")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Create FastAPI application
app = FastAPI(
    title="SERVE Orchestrator Service",
    description="Central coordination layer for SERVE AI",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(orchestrator_router, prefix="/api/orchestrator")


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        service="serve-orchestrator",
        status="healthy",
        version="1.0.0",
        timestamp=datetime.utcnow()
    )


@app.api_route("/api/mcp/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def mcp_proxy(path: str, request: Request):
    """Proxy all /api/mcp/* requests to the MCP service. Requires JWT (when auth enabled)."""
    from app.core.auth import AUTH_ENABLED, get_current_user
    if AUTH_ENABLED:
        try:
            await get_current_user(request)
        except Exception:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

    target_url = f"{MCP_SERVICE_URL}/api/{path}"
    params = dict(request.query_params)
    body = await request.body()
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }
    async with httpx.AsyncClient() as client:
        proxy_response = await client.request(
            method=request.method,
            url=target_url,
            params=params,
            content=body,
            headers=headers,
            timeout=30.0
        )
    return Response(
        content=proxy_response.content,
        status_code=proxy_response.status_code,
        headers=dict(proxy_response.headers),
        media_type=proxy_response.headers.get("content-type")
    )


@app.get("/api/")
async def root():
    """Root endpoint"""
    return {
        "service": "SERVE Orchestrator Service",
        "version": "1.0.0",
        "description": "Central coordination layer for SERVE AI",
        "endpoints": [
            "/api/interact - Process user interaction",
            "/api/session/{id} - Get session state",
            "/api/sessions - List all sessions",
            "/api/health - Health check"
        ]
    }


# ── WhatsApp Cloud API webhook ────────────────────────────────────────────────

_WA_TOKEN           = os.environ.get("WHATSAPP_TOKEN", "")
_WA_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
_WA_APP_SECRET      = os.environ.get("WHATSAPP_APP_SECRET", "")
_WA_VERIFY_TOKEN    = os.environ.get("WHATSAPP_VERIFY_TOKEN", "serve_verify_token")
_WA_GRAPH_URL       = "https://graph.facebook.com/v18.0"

# phone → orchestrator session_id
_wa_sessions: dict = {}


async def _wa_send(to: str, text: str) -> bool:
    """Returns whether the send actually succeeded. Existing call sites all
    discard the return value (fire-and-forget within the inbound reply cycle),
    so adding this is purely additive — it only matters to internal_notify,
    which needs to report send failures honestly rather than assuming success."""
    if not _WA_TOKEN or not _WA_PHONE_NUMBER_ID:
        logger.warning("WhatsApp not configured — skipping send")
        return False
    url = f"{_WA_GRAPH_URL}/{_WA_PHONE_NUMBER_ID}/messages"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.post(
                url,
                headers={"Authorization": f"Bearer {_WA_TOKEN}", "Content-Type": "application/json"},
                json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}},
            )
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"WhatsApp send failed: {e}")
            return False


import re as _re

_VIDEO_TAG_RE = _re.compile(r'\[VIDEO:(.*?)\|(.*?)\]')


async def _wa_send_rich(to: str, text: str) -> None:
    """
    Send a message to WhatsApp, handling [VIDEO:url|caption] tags.
    Videos are uploaded to WhatsApp and sent as native video messages.
    Text around the tags is sent as regular text messages.
    """
    from app.channel.wa_media import fetch_and_send_video

    # Find all video tags
    video_matches = list(_VIDEO_TAG_RE.finditer(text))

    if not video_matches:
        # No video tags — send as plain text
        await _wa_send(to, text)
        return

    # Strip video tags from text and send the text part first
    text_only = _VIDEO_TAG_RE.sub('', text).strip()
    if text_only:
        await _wa_send(to, text_only)

    # Send each video as a native WhatsApp video message
    for match in video_matches:
        video_url = match.group(1)
        # Rewrite localhost URLs to Docker internal hostname for container-to-container fetch
        video_url = video_url.replace("http://localhost:8002", "http://serve-onboarding-agent-service:8002")
        caption = match.group(2)
        logger.info(f"Sending WhatsApp video: url={video_url}, caption={caption}")
        ok = await fetch_and_send_video(to, video_url, caption)
        if not ok:
            logger.warning(f"WhatsApp video send failed for {video_url} — sending caption as text fallback")
            await _wa_send(to, f"🎥 {caption}")


async def _wa_mark_read(message_id: str) -> None:
    """Mark a message as read (blue ticks) and show typing indicator to the sender."""
    if not _WA_TOKEN or not _WA_PHONE_NUMBER_ID:
        return
    url = f"{_WA_GRAPH_URL}/{_WA_PHONE_NUMBER_ID}/messages"
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.post(
                url,
                headers={"Authorization": f"Bearer {_WA_TOKEN}", "Content-Type": "application/json"},
                json={
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": message_id,
                    "typing_indicator": {"type": "text"},
                },
            )
        except Exception as e:
            logger.warning(f"WhatsApp mark-read failed: {e}")


@app.get("/api/whatsapp/webhook")
async def wa_verify(request: Request):
    """Meta webhook verification handshake."""
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == _WA_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified")
        return PlainTextResponse(p.get("hub.challenge", ""))
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/api/whatsapp/webhook")
async def wa_receive(request: Request):
    """Receive inbound messages from Meta Cloud API."""
    body_bytes = await request.body()

    # Signature verification
    if _WA_APP_SECRET:
        sig = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(_WA_APP_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        data = json.loads(body_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                if msg.get("type") != "text":
                    continue
                phone      = msg.get("from", "")
                text       = msg.get("text", {}).get("body", "").strip()
                message_id = msg.get("id", "")
                if not phone or not text:
                    continue

                # Option 2: mark message as read immediately (shows blue ticks)
                if message_id:
                    asyncio.create_task(_wa_mark_read(message_id))

                if text.lower() in ("reset", "restart", "start over", "new"):
                    _wa_sessions.pop(phone, None)
                    await _wa_send(phone, "Session reset! Send a message to start fresh.")
                    continue

                session_id = _wa_sessions.get(phone)

                # Option 3: send instant ack on first message (no session yet)
                # so user knows we received it while resolution runs in background
                if not session_id:
                    asyncio.create_task(_wa_send(phone, "Ek second... 🙏"))

                # Detect persona from first message (no session yet)
                # Mimics the UI role selection — keyword-based
                def _detect_persona(msg: str):
                    lower = msg.lower()
                    recommended_signals = [
                        "i was recommended", "someone recommended", "recommended volunteer",
                        "mujhe recommend kiya", "recommend kiya gaya",
                        "referral", "i got a referral", "referred by",
                        "kisi ne bataya", "kisi ne bheja",
                    ]
                    volunteer_signals = [
                        "returning volunteer", "pehle padhaya",
                        "continue teaching", "wapas", "re-engage", "last year",
                        "pichle saal", "continue karna", "teaching again",
                    ]
                    coordinator_signals = [
                        "need", "school", "coordinator", "teacher chahiye",
                        "register", "raise need", "padhane wale", "volunteer chahiye",
                    ]
                    # Check recommended FIRST — "recommended volunteer" contains "volunteer"
                    # which would falsely match returning volunteer if checked second
                    if any(s in lower for s in recommended_signals):
                        return PersonaType.RECOMMENDED_VOLUNTEER
                    if any(s in lower for s in volunteer_signals):
                        return PersonaType.RETURNING_VOLUNTEER
                    if any(s in lower for s in coordinator_signals):
                        return PersonaType.NEED_COORDINATOR
                    return None

                # For new sessions, detect from message; for existing, let orchestrator handle
                detected_persona = _detect_persona(text) if not session_id else None

                async def _process(phone=phone, text=text, session_id=session_id, detected_persona=detected_persona):
                    try:
                        req = InteractionRequest(
                            session_id=session_id,
                            message=text,
                            channel=ChannelType.WHATSAPP,
                            persona=detected_persona,  # from message keywords or None (let resolver decide)
                            channel_metadata={
                                "phone_number": phone,
                                "volunteer_phone": phone,
                            },
                        )
                        resp = await orchestration_service.process_interaction(req)
                        _wa_sessions[phone] = str(resp.session_id)

                        # Send preliminary message as a separate bubble if present
                        if getattr(resp, 'preliminary_message', None):
                            await _wa_send_rich(phone, resp.preliminary_message)

                        await _wa_send_rich(phone, resp.assistant_message)

                        # Auto-continue: agent wants a follow-up turn (e.g. ack → real response)
                        if getattr(resp, 'auto_continue', False):
                            followup_req = InteractionRequest(
                                session_id=resp.session_id,
                                message="__auto_continue__",
                                channel=ChannelType.WHATSAPP,
                                channel_metadata={
                                    "phone_number": phone,
                                    "volunteer_phone": phone,
                                },
                            )
                            followup_resp = await orchestration_service.process_interaction(followup_req)
                            if getattr(followup_resp, 'preliminary_message', None):
                                await _wa_send_rich(phone, followup_resp.preliminary_message)
                            if followup_resp.assistant_message:
                                await _wa_send_rich(phone, followup_resp.assistant_message)
                    except Exception as e:
                        logger.error(f"Error handling WhatsApp message from {phone[:6]}***: {e}")
                        await _wa_send(phone, "Something went wrong. Please try again in a moment.")

                asyncio.create_task(_process())

    return {"status": "ok"}


@app.get("/api/whatsapp/status")
async def wa_status():
    return {
        "enabled": bool(_WA_TOKEN and _WA_PHONE_NUMBER_ID),
        "active_sessions": len(_wa_sessions),
        "phone_number_id_configured": bool(_WA_PHONE_NUMBER_ID),
        "token_configured": bool(_WA_TOKEN),
    }


@app.post("/api/internal/notify")
async def internal_notify(request: Request):
    """
    Internal-only: send a WhatsApp message to an arbitrary phone number, outside
    the normal inbound-reply cycle. Used by the delivery assistant's
    notify_linked_stakeholder to reach a coordinator who isn't the current chat
    participant. Reuses the existing, already-tested _wa_send — does not touch
    wa_receive, _wa_sessions, or any inbound routing logic. Trusts the internal
    docker network the same way agent-to-agent calls already do; body is
    {"phone": str, "message": str}, both required. Message content is expected
    to be a fixed template built by the caller — this endpoint does not
    generate or alter it.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    phone = (body.get("phone") or "").strip()
    message = (body.get("message") or "").strip()
    if not phone or not message:
        raise HTTPException(status_code=422, detail="phone and message are both required")
    if not _WA_TOKEN or not _WA_PHONE_NUMBER_ID:
        logger.warning("internal_notify: WhatsApp not configured — cannot send")
        return {"status": "not_configured"}
    ok = await _wa_send(phone, message)
    if not ok:
        raise HTTPException(status_code=502, detail="WhatsApp send failed")
    return {"status": "sent"}


@app.on_event("startup")
async def startup_event():
    logger.info("Starting SERVE Orchestrator Service...")
    # Launch background agent health-probe loop.
    # Probes every AGENT_HEALTH_PROBE_INTERVAL seconds (default 30s) and
    # updates each agent's 'healthy' flag so the router always has fresh data.
    asyncio.create_task(agent_router.registry.start_health_probing())


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down SERVE Orchestrator Service...")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8001)),
        reload=True
    )
