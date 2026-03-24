"""
SERVE AI - WhatsApp Channel Adapter
Meta WhatsApp Business Cloud API integration.

Architecture:
- GET /webhook  — Meta verification handshake (hub.challenge)
- POST /webhook — Incoming messages from Meta Cloud API (JSON payload)
- Replies sent via Graph API POST (not in webhook response body)
- Phone number used as session identifier
"""
import os
import hmac
import hashlib
import logging
import httpx
from typing import Optional, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

WHATSAPP_TOKEN           = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_APP_SECRET      = os.environ.get("WHATSAPP_APP_SECRET", "")
WHATSAPP_VERIFY_TOKEN    = os.environ.get("WHATSAPP_VERIFY_TOKEN", "serve_verify_token")

GRAPH_API_URL = "https://graph.facebook.com/v18.0"

if WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID:
    logger.info("WhatsApp Cloud API adapter initialised")
else:
    logger.warning("WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID not set — WhatsApp disabled")


# ── Phone-to-Session Mapping ──────────────────────────────────────────────────

class PhoneSessionManager:
    """Maps WhatsApp phone numbers to orchestrator session IDs."""

    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def get(self, phone: str) -> Optional[Dict[str, Any]]:
        return self._sessions.get(phone)

    def create(self, phone: str, session_id: str, workflow: str = "need_coordination") -> Dict[str, Any]:
        session = {
            "phone_number": phone,
            "orchestrator_session_id": session_id,
            "workflow": workflow,
            "created_at": datetime.utcnow().isoformat(),
            "last_activity": datetime.utcnow().isoformat(),
            "message_count": 0,
        }
        self._sessions[phone] = session
        logger.info(f"New WhatsApp session: {phone[:6]}*** → {session_id[:8]}…")
        return session

    def update(self, phone: str, session_id: str = None):
        s = self._sessions.get(phone)
        if s:
            s["last_activity"] = datetime.utcnow().isoformat()
            s["message_count"] += 1
            if session_id:
                s["orchestrator_session_id"] = session_id

    def clear(self, phone: str) -> bool:
        if phone in self._sessions:
            del self._sessions[phone]
            return True
        return False

    def all(self) -> Dict[str, Dict[str, Any]]:
        return self._sessions.copy()


phone_session_manager = PhoneSessionManager()


# ── Send reply via Graph API ──────────────────────────────────────────────────

async def send_whatsapp_message(to_number: str, message: str) -> bool:
    """Send a text message via WhatsApp Cloud API."""
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        logger.error("WhatsApp not configured — cannot send message")
        return False

    # Strip any whatsapp: prefix if present
    to_number = to_number.replace("whatsapp:", "")

    url = f"{GRAPH_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message},
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            logger.info(f"Message sent to {to_number[:6]}***: {resp.json()}")
            return True
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
        return False


# ── Signature verification ────────────────────────────────────────────────────

def _verify_signature(body: bytes, signature_header: str) -> bool:
    """Verify X-Hub-Signature-256 from Meta."""
    if not WHATSAPP_APP_SECRET:
        return True  # Skip in dev if secret not set
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        WHATSAPP_APP_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header[7:])


# ── Message handler ───────────────────────────────────────────────────────────

async def _handle_message(phone: str, message_body: str, orchestrator_interact_func) -> None:
    """Process one inbound message and send reply."""
    if message_body.lower().strip() in ("reset", "restart", "start over", "new"):
        phone_session_manager.clear(phone)
        await send_whatsapp_message(phone, "Session reset! Send a message to start fresh.")
        return

    session = phone_session_manager.get(phone)
    session_id = session["orchestrator_session_id"] if session else None

    try:
        response = await orchestrator_interact_func(
            session_id=session_id,
            message=message_body,
            channel="whatsapp",
            persona="need_coordinator",
            channel_metadata={"phone_number": phone},
        )

        new_session_id = response.get("session_id")
        if session:
            phone_session_manager.update(phone, new_session_id)
        else:
            phone_session_manager.create(
                phone=phone,
                session_id=new_session_id or "",
                workflow=response.get("workflow", "need_coordination"),
            )

        reply = response.get("assistant_message") or "I'm here to help. Please try again."
        await send_whatsapp_message(phone, reply)

    except Exception as e:
        logger.error(f"Error handling message from {phone[:6]}***: {e}")
        await send_whatsapp_message(phone, "I'm sorry, something went wrong. Please try again in a moment.")


# ── FastAPI Router ────────────────────────────────────────────────────────────

whatsapp_router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])

# Orchestrator function injected at startup
_orchestrator_interact = None


def set_orchestrator(interact_func):
    """Called from main server to wire up the orchestrator."""
    global _orchestrator_interact
    _orchestrator_interact = interact_func


@whatsapp_router.get("/webhook")
async def verify_webhook(request: Request):
    """Meta webhook verification handshake."""
    params = request.query_params
    mode      = params.get("hub.mode")
    token     = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified")
        return PlainTextResponse(challenge)

    logger.warning(f"Webhook verification failed: mode={mode} token={token}")
    raise HTTPException(status_code=403, detail="Verification failed")


@whatsapp_router.post("/webhook")
async def receive_webhook(request: Request):
    """Receive inbound messages from Meta Cloud API."""
    body_bytes = await request.body()

    # Signature check
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(body_bytes, sig):
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Meta sends a nested structure — walk to the message
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                msg_type = msg.get("type")
                if msg_type != "text":
                    # Ignore non-text (images, audio, etc.) for now
                    continue

                phone = msg.get("from", "")
                body  = msg.get("text", {}).get("body", "").strip()

                if phone and body and _orchestrator_interact:
                    await _handle_message(phone, body, _orchestrator_interact)

    # Meta expects a 200 OK immediately — reply is sent separately via Graph API
    return {"status": "ok"}


@whatsapp_router.get("/status")
async def whatsapp_status():
    return {
        "enabled": bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID),
        "phone_number_id": WHATSAPP_PHONE_NUMBER_ID or None,
        "active_sessions": len(phone_session_manager.all()),
        "configuration": {
            "token_configured":           bool(WHATSAPP_TOKEN),
            "phone_number_id_configured": bool(WHATSAPP_PHONE_NUMBER_ID),
            "app_secret_configured":      bool(WHATSAPP_APP_SECRET),
            "verify_token_configured":    bool(WHATSAPP_VERIFY_TOKEN),
        },
    }


@whatsapp_router.get("/sessions")
async def list_sessions():
    sessions = phone_session_manager.all()
    masked = {}
    for phone, data in sessions.items():
        key = phone[:6] + "***" + phone[-2:] if len(phone) > 8 else "***"
        masked[key] = {
            "session_id":    data["orchestrator_session_id"][:8] + "…",
            "workflow":      data["workflow"],
            "message_count": data["message_count"],
            "last_activity": data["last_activity"],
        }
    return {"sessions": masked, "total": len(sessions)}


@whatsapp_router.post("/test-send")
async def test_send(to_number: str, message: str):
    """Admin: send a test message."""
    if not WHATSAPP_TOKEN:
        raise HTTPException(status_code=503, detail="WhatsApp not configured")
    success = await send_whatsapp_message(to_number, message)
    return {"success": success, "to": to_number}
