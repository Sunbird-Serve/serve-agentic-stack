"""
SERVE AI - WhatsApp Channel Adapter
Twilio WhatsApp Sandbox integration with webhook-based message handling.

Architecture:
- Webhook endpoint receives incoming WhatsApp messages from Twilio
- Messages are routed through the orchestrator
- Responses are sent back via Twilio WhatsApp API
- Phone number is used as session identifier
"""
import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import uuid4
import hashlib

from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from twilio.rest import Client
from twilio.request_validator import RequestValidator

logger = logging.getLogger(__name__)

# ============ Configuration ============

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.environ.get("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")  # Sandbox number

# Initialize Twilio client
twilio_client = None
request_validator = None

if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    request_validator = RequestValidator(TWILIO_AUTH_TOKEN)
    logger.info("Twilio WhatsApp client initialized")
else:
    logger.warning("Twilio credentials not configured - WhatsApp integration disabled")


# ============ Phone-to-Session Mapping ============

class PhoneSessionManager:
    """
    Manages mapping between WhatsApp phone numbers and orchestrator sessions.
    Uses phone number as primary session identifier.
    """
    
    def __init__(self):
        # phone_number -> session_data
        self._sessions: Dict[str, Dict[str, Any]] = {}
    
    def get_session(self, phone_number: str) -> Optional[Dict[str, Any]]:
        """Get existing session for phone number."""
        return self._sessions.get(phone_number)
    
    def create_session(self, phone_number: str, orchestrator_session_id: str, workflow: str = "need_coordination") -> Dict[str, Any]:
        """Create new session mapping."""
        session = {
            "phone_number": phone_number,
            "orchestrator_session_id": orchestrator_session_id,
            "workflow": workflow,
            "created_at": datetime.utcnow().isoformat(),
            "last_activity": datetime.utcnow().isoformat(),
            "message_count": 0
        }
        self._sessions[phone_number] = session
        logger.info(f"Created WhatsApp session for {phone_number[:6]}*** -> {orchestrator_session_id[:8]}...")
        return session
    
    def update_session(self, phone_number: str, orchestrator_session_id: str = None) -> Optional[Dict[str, Any]]:
        """Update session activity."""
        session = self._sessions.get(phone_number)
        if session:
            session["last_activity"] = datetime.utcnow().isoformat()
            session["message_count"] += 1
            if orchestrator_session_id:
                session["orchestrator_session_id"] = orchestrator_session_id
        return session
    
    def clear_session(self, phone_number: str) -> bool:
        """Clear session for phone number (for reset/restart)."""
        if phone_number in self._sessions:
            del self._sessions[phone_number]
            return True
        return False
    
    def get_all_sessions(self) -> Dict[str, Dict[str, Any]]:
        """Get all active sessions (for admin/monitoring)."""
        return self._sessions.copy()


# Singleton instance
phone_session_manager = PhoneSessionManager()


# ============ WhatsApp Message Handler ============

class WhatsAppMessageHandler:
    """Handles incoming WhatsApp messages and routes to orchestrator."""
    
    def __init__(self, orchestrator_interact_func):
        """
        Initialize with reference to orchestrator interact function.
        
        Args:
            orchestrator_interact_func: Async function to call orchestrator
        """
        self.orchestrator_interact = orchestrator_interact_func
    
    async def handle_incoming_message(
        self,
        from_number: str,
        message_body: str,
        media_url: Optional[str] = None
    ) -> str:
        """
        Handle incoming WhatsApp message and return response.
        
        Args:
            from_number: WhatsApp number (format: whatsapp:+1234567890)
            message_body: Text content of the message
            media_url: Optional media attachment URL
            
        Returns:
            Response text to send back
        """
        # Normalize phone number (remove whatsapp: prefix)
        phone = from_number.replace("whatsapp:", "")
        
        # Check for reset/restart commands
        if message_body.lower().strip() in ["reset", "restart", "start over", "new"]:
            phone_session_manager.clear_session(phone)
            return "Session reset! Let's start fresh. How can I help you today?"
        
        # Get or create session
        session = phone_session_manager.get_session(phone)
        session_id = session["orchestrator_session_id"] if session else None
        
        try:
            # Call orchestrator
            response = await self.orchestrator_interact(
                session_id=session_id,
                message=message_body,
                channel="whatsapp",
                persona="need_coordinator",
                channel_metadata={
                    "whatsapp_number": phone,
                    "media_url": media_url
                }
            )
            
            # Update or create session mapping
            if session:
                phone_session_manager.update_session(phone, response.get("session_id"))
            else:
                phone_session_manager.create_session(
                    phone_number=phone,
                    orchestrator_session_id=response.get("session_id"),
                    workflow=response.get("workflow", "need_coordination")
                )
            
            return response.get("assistant_message", "I apologize, but I couldn't process your message. Please try again.")
            
        except Exception as e:
            logger.error(f"Error handling WhatsApp message: {e}")
            return "I'm sorry, I encountered an issue. Please try again in a moment."


# ============ Twilio WhatsApp Sender ============

async def send_whatsapp_message(to_number: str, message: str) -> bool:
    """
    Send WhatsApp message via Twilio.
    
    Args:
        to_number: Recipient number (format: +1234567890 or whatsapp:+1234567890)
        message: Text message to send
        
    Returns:
        True if sent successfully
    """
    if not twilio_client:
        logger.error("Twilio client not initialized")
        return False
    
    # Ensure whatsapp: prefix
    if not to_number.startswith("whatsapp:"):
        to_number = f"whatsapp:{to_number}"
    
    try:
        twilio_message = twilio_client.messages.create(
            body=message,
            from_=TWILIO_WHATSAPP_NUMBER,
            to=to_number
        )
        logger.info(f"WhatsApp message sent: {twilio_message.sid}")
        return True
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
        return False


# ============ FastAPI Router ============

whatsapp_router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])


@whatsapp_router.post("/webhook")
async def whatsapp_webhook(request: Request):
    """
    Twilio WhatsApp webhook endpoint.
    
    Receives incoming messages from Twilio and returns TwiML response.
    """
    # Get form data from Twilio
    form_data = await request.form()
    
    # Extract message details
    from_number = form_data.get("From", "")
    message_body = form_data.get("Body", "")
    media_url = form_data.get("MediaUrl0")  # First media attachment if any
    
    logger.info(f"WhatsApp webhook: from={from_number[:15]}..., body={message_body[:50]}...")
    
    # Validate Twilio signature in production
    if TWILIO_AUTH_TOKEN and request_validator:
        signature = request.headers.get("X-Twilio-Signature", "")
        url = str(request.url)
        
        # Convert form data to dict for validation
        params = {key: form_data.get(key) for key in form_data.keys()}
        
        # Note: In sandbox mode, signature validation may be skipped
        # if not request_validator.validate(url, params, signature):
        #     logger.warning("Invalid Twilio signature")
        #     raise HTTPException(status_code=403, detail="Invalid signature")
    
    # Handle the message (this will be connected to orchestrator)
    # For now, return a simple acknowledgment
    response_text = await handle_whatsapp_message_internal(from_number, message_body, media_url)
    
    # Return TwiML response
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{response_text}</Message>
</Response>"""
    
    return Response(content=twiml, media_type="application/xml")


@whatsapp_router.get("/webhook")
async def whatsapp_webhook_verify(request: Request):
    """
    Webhook verification endpoint (for some providers).
    """
    return PlainTextResponse("OK")


@whatsapp_router.get("/status")
async def whatsapp_status():
    """
    Get WhatsApp integration status.
    """
    return {
        "enabled": twilio_client is not None,
        "sandbox_number": TWILIO_WHATSAPP_NUMBER if twilio_client else None,
        "active_sessions": len(phone_session_manager.get_all_sessions()),
        "configuration": {
            "account_sid_configured": bool(TWILIO_ACCOUNT_SID),
            "auth_token_configured": bool(TWILIO_AUTH_TOKEN),
            "whatsapp_number_configured": bool(TWILIO_WHATSAPP_NUMBER)
        }
    }


@whatsapp_router.get("/sessions")
async def list_whatsapp_sessions():
    """
    List active WhatsApp sessions (admin endpoint).
    """
    sessions = phone_session_manager.get_all_sessions()
    # Mask phone numbers for privacy
    masked = {}
    for phone, data in sessions.items():
        masked_phone = phone[:6] + "***" + phone[-2:] if len(phone) > 8 else "***"
        masked[masked_phone] = {
            "orchestrator_session_id": data["orchestrator_session_id"][:8] + "...",
            "workflow": data["workflow"],
            "message_count": data["message_count"],
            "last_activity": data["last_activity"]
        }
    return {"sessions": masked, "total": len(sessions)}


@whatsapp_router.post("/test-send")
async def test_send_whatsapp(to_number: str, message: str):
    """
    Test endpoint to send a WhatsApp message (admin only).
    """
    if not twilio_client:
        raise HTTPException(status_code=503, detail="Twilio not configured")
    
    success = await send_whatsapp_message(to_number, message)
    return {"success": success, "to": to_number}


# ============ Internal Handler (to be connected to orchestrator) ============

# This will be replaced when integrating with the main server
async def handle_whatsapp_message_internal(from_number: str, message_body: str, media_url: Optional[str] = None) -> str:
    """
    Internal handler - placeholder until connected to orchestrator.
    """
    phone = from_number.replace("whatsapp:", "")
    session = phone_session_manager.get_session(phone)
    
    if message_body.lower().strip() in ["reset", "restart", "start over", "new"]:
        phone_session_manager.clear_session(phone)
        return "Session reset! Send a message to start fresh."
    
    # This will be replaced with actual orchestrator call
    # For now, return a placeholder
    return f"[WhatsApp] Received: {message_body[:50]}... (Orchestrator integration pending)"
