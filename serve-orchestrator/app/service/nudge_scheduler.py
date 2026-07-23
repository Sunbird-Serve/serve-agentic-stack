"""
SERVE Orchestrator — Nudge Scheduler

Background task that sends reminder messages to inactive WhatsApp sessions.

Schedule:
  Nudge #1: 1 hour after last message
  Nudge #2: 8 hours after last message
  Nudge #3: 24 hours after last message (final)

After 3 nudges with no reply, session is auto-paused.
Volunteer can reply "stop" to opt out permanently.

Runs every NUDGE_CHECK_INTERVAL_MINUTES (default 5 min).
Only sends to WhatsApp channel (web UI can't push).
Respects quiet hours (default 9pm-8am).
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
NUDGE_ENABLED = os.environ.get("NUDGE_ENABLED", "true").lower() == "true"
NUDGE_DELAY_1_MINUTES = int(os.environ.get("NUDGE_DELAY_1_MINUTES", "60"))
NUDGE_DELAY_2_MINUTES = int(os.environ.get("NUDGE_DELAY_2_MINUTES", "480"))
NUDGE_DELAY_3_MINUTES = int(os.environ.get("NUDGE_DELAY_3_MINUTES", "1440"))
NUDGE_QUIET_HOURS_START = int(os.environ.get("NUDGE_QUIET_HOURS_START", "21"))
NUDGE_QUIET_HOURS_END = int(os.environ.get("NUDGE_QUIET_HOURS_END", "8"))
NUDGE_CHECK_INTERVAL_MINUTES = int(os.environ.get("NUDGE_CHECK_INTERVAL_MINUTES", "5"))

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://serve-mcp-server:8004")

# WhatsApp config (same as main.py)
_WA_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
_WA_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
_WA_GRAPH_URL = "https://graph.facebook.com/v18.0"

# ── Nudge messages ────────────────────────────────────────────────────────────
NUDGE_MESSAGES = {
    1: (
        "Hi! Looks like we paused mid-conversation. Would you like to continue?\n\n"
        "Reply:\n"
        "▶️ *continue* — pick up where you left off\n"
        "⏰ *later* — remind me in a few hours\n"
        "🚫 *stop* — don't send reminders"
    ),
    2: (
        "Hey! Just a quick check-in — your progress is saved and we're ready "
        "whenever you are. Reply anytime to continue, or 'stop' for no more reminders."
    ),
    3: (
        "Hi! We're still here whenever you're ready. Your progress is saved — "
        "just message anytime. This is our last reminder. 🙂"
    ),
}

# ── Nudge delays (minutes from original silence) ─────────────────────────────
NUDGE_DELAYS = {
    1: NUDGE_DELAY_1_MINUTES,
    2: NUDGE_DELAY_2_MINUTES,
    3: NUDGE_DELAY_3_MINUTES,
}


def _is_quiet_hour() -> bool:
    """Check if current time is within quiet hours (don't send nudges)."""
    now = datetime.utcnow()
    # Simple UTC-based check. For IST, add 5.5 hours.
    # TODO: Make timezone-aware for production
    ist_hour = (now.hour + 5) % 24  # rough IST approximation
    if NUDGE_QUIET_HOURS_START > NUDGE_QUIET_HOURS_END:
        # Wraps midnight: e.g., 21-8 means quiet from 9pm to 8am
        return ist_hour >= NUDGE_QUIET_HOURS_START or ist_hour < NUDGE_QUIET_HOURS_END
    else:
        return NUDGE_QUIET_HOURS_START <= ist_hour < NUDGE_QUIET_HOURS_END


async def _send_whatsapp(to: str, text: str) -> bool:
    """Send a WhatsApp text message."""
    if not _WA_TOKEN or not _WA_PHONE_NUMBER_ID:
        logger.warning("[nudge] WhatsApp not configured — cannot send nudge")
        return False

    url = f"{_WA_GRAPH_URL}/{_WA_PHONE_NUMBER_ID}/messages"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                url,
                headers={"Authorization": f"Bearer {_WA_TOKEN}", "Content-Type": "application/json"},
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {"body": text},
                },
            )
            r.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"[nudge] WhatsApp send failed to {to[:6]}***: {e}")
        return False


async def _get_sessions_needing_nudge() -> List[Dict]:
    """
    Query MCP server for active WhatsApp sessions that have gone silent.
    Returns sessions that need their next nudge.
    """
    try:
        from mcp.client.session import ClientSession
        from mcp.client.sse import sse_client
        import json

        sse_url = f"{MCP_SERVER_URL}/sse"
        async with sse_client(url=sse_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("list_sessions", arguments={
                    "params": {"status": "active", "limit": 200}
                })
                for item in result.content:
                    if hasattr(item, "text"):
                        data = json.loads(item.text)
                        return data.get("sessions", [])
        return []
    except Exception as e:
        logger.error(f"[nudge] Failed to query sessions: {e}")
        return []


async def _get_pending_nudges_for_session(session_id: str) -> List[Dict]:
    """Check if there are already pending/sent nudges for a session."""
    # For now, use a simple in-memory tracker.
    # In production, this would query the nudge_queue table.
    return _nudge_tracker.get(session_id, [])


# ── In-memory nudge tracker (simple, single-instance) ─────────────────────────
# Maps session_id → list of nudge records
# In production, replace with DB queries to nudge_queue table
_nudge_tracker: Dict[str, List[Dict]] = {}


def cancel_nudges_for_session(session_id: str) -> None:
    """Cancel all pending nudges for a session (called when volunteer messages)."""
    if session_id in _nudge_tracker:
        del _nudge_tracker[session_id]
        logger.info(f"[nudge] Cancelled pending nudges for session {session_id[:8]}...")


def mark_do_not_disturb(session_id: str) -> None:
    """Mark a session as do-not-disturb (volunteer said 'stop')."""
    _nudge_tracker[session_id] = [{"do_not_disturb": True}]
    logger.info(f"[nudge] Session {session_id[:8]}... marked as DO_NOT_DISTURB")


def is_do_not_disturb(session_id: str) -> bool:
    """Check if a session is marked do-not-disturb."""
    records = _nudge_tracker.get(session_id, [])
    return any(r.get("do_not_disturb") for r in records)


def get_nudge_count(session_id: str) -> int:
    """Get how many nudges have been sent for this session's current silence window."""
    records = _nudge_tracker.get(session_id, [])
    return sum(1 for r in records if r.get("sent") and not r.get("do_not_disturb"))


def schedule_nudge(session_id: str, phone: str, nudge_number: int, send_at: datetime) -> None:
    """Schedule a nudge for a session."""
    if session_id not in _nudge_tracker:
        _nudge_tracker[session_id] = []
    _nudge_tracker[session_id].append({
        "nudge_number": nudge_number,
        "phone": phone,
        "scheduled_at": send_at,
        "sent": False,
        "do_not_disturb": False,
    })
    logger.info(f"[nudge] Scheduled nudge #{nudge_number} for session {session_id[:8]}... at {send_at.isoformat()}")


async def _process_pending_nudges() -> int:
    """Process all pending nudges that are due. Returns count of nudges sent."""
    sent_count = 0
    now = datetime.utcnow()

    if _is_quiet_hour():
        return 0

    for session_id, records in list(_nudge_tracker.items()):
        if any(r.get("do_not_disturb") for r in records):
            continue

        for record in records:
            if record.get("sent") or record.get("do_not_disturb"):
                continue
            if record["scheduled_at"] <= now:
                # Time to send
                nudge_num = record["nudge_number"]
                phone = record["phone"]
                message = NUDGE_MESSAGES.get(nudge_num, NUDGE_MESSAGES[1])

                success = await _send_whatsapp(phone, message)
                if success:
                    record["sent"] = True
                    record["sent_at"] = now
                    sent_count += 1
                    logger.info(f"[nudge] Sent nudge #{nudge_num} to {phone[:6]}*** (session {session_id[:8]}...)")

                    # Schedule next nudge if not the last
                    if nudge_num < 3:
                        next_num = nudge_num + 1
                        next_delay = NUDGE_DELAYS[next_num]
                        next_at = now + timedelta(minutes=next_delay - NUDGE_DELAYS[nudge_num])
                        schedule_nudge(session_id, phone, next_num, next_at)
                else:
                    logger.warning(f"[nudge] Failed to send nudge #{nudge_num} to {phone[:6]}***")

    return sent_count


async def check_and_schedule_new_nudges() -> None:
    """
    Check active WhatsApp sessions for silence and schedule first nudges.
    Called by the background loop.
    """
    sessions = await _get_sessions_needing_nudge()
    now = datetime.utcnow()

    for session in sessions:
        session_id = session.get("id", "")
        channel = session.get("channel", "")
        status = session.get("status", "")
        last_msg = session.get("last_message_at")

        # Only WhatsApp active sessions
        if channel != "whatsapp" or status != "active":
            continue

        # Skip if already tracked or do-not-disturb
        if session_id in _nudge_tracker:
            continue

        # Check silence duration
        if not last_msg:
            continue

        try:
            last_msg_time = datetime.fromisoformat(last_msg.replace("Z", "+00:00").replace("+00:00", ""))
        except (ValueError, TypeError):
            continue

        silence_minutes = (now - last_msg_time).total_seconds() / 60

        if silence_minutes >= NUDGE_DELAY_1_MINUTES:
            # Get phone from channel_metadata
            ch_meta = session.get("channel_metadata") or {}
            phone = (
                ch_meta.get("volunteer_phone")
                or ch_meta.get("phone_number")
                or session.get("actor_id", "")
            )
            if phone and phone != "dev-user-00000000-0000-0000-0000-000000000000":
                schedule_nudge(session_id, phone, 1, now)


async def start_nudge_scheduler() -> None:
    """
    Background loop — runs every NUDGE_CHECK_INTERVAL_MINUTES.
    Checks for sessions needing nudges and sends due nudges.
    """
    if not NUDGE_ENABLED:
        logger.info("[nudge] Nudge scheduler DISABLED (NUDGE_ENABLED=false)")
        return

    if not _WA_TOKEN or not _WA_PHONE_NUMBER_ID:
        logger.warning("[nudge] Nudge scheduler disabled — WhatsApp not configured")
        return

    logger.info(
        f"[nudge] Nudge scheduler starting — "
        f"check every {NUDGE_CHECK_INTERVAL_MINUTES}min, "
        f"delays: {NUDGE_DELAY_1_MINUTES}m/{NUDGE_DELAY_2_MINUTES}m/{NUDGE_DELAY_3_MINUTES}m, "
        f"quiet hours: {NUDGE_QUIET_HOURS_START}:00-{NUDGE_QUIET_HOURS_END}:00 IST"
    )

    while True:
        try:
            await check_and_schedule_new_nudges()
            sent = await _process_pending_nudges()
            if sent:
                logger.info(f"[nudge] Cycle complete: {sent} nudges sent")
        except Exception as e:
            logger.error(f"[nudge] Scheduler error: {e}")

        await asyncio.sleep(NUDGE_CHECK_INTERVAL_MINUTES * 60)
