"""
Dashboard stats service — read-only queries for the Tech Team dashboard.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import select, func, and_, desc

from services.database import (
    get_db, is_db_healthy,
    Session as DBSession,
    NeedDraft,
    ConversationMessage,
)

logger = logging.getLogger(__name__)


async def get_dashboard_stats() -> Dict[str, Any]:
    """Return aggregated stats for the tech dashboard."""
    from services.database import check_db_health
    db_ok = await check_db_health()
    if not db_ok:
        return {"status": "error", "error": "Database not available"}

    try:
        async with get_db() as db:
            now = datetime.utcnow()
            day_ago   = now - timedelta(hours=24)
            week_ago  = now - timedelta(days=7)

            # ── Session counts ────────────────────────────────────────────────
            total_sessions = (await db.execute(
                select(func.count()).select_from(DBSession)
            )).scalar() or 0

            active_sessions = (await db.execute(
                select(func.count()).select_from(DBSession)
                .where(DBSession.status == "active")
            )).scalar() or 0

            sessions_today = (await db.execute(
                select(func.count()).select_from(DBSession)
                .where(DBSession.created_at >= day_ago)
            )).scalar() or 0

            sessions_week = (await db.execute(
                select(func.count()).select_from(DBSession)
                .where(DBSession.created_at >= week_ago)
            )).scalar() or 0

            # ── Sessions by channel ───────────────────────────────────────────
            channel_rows = (await db.execute(
                select(DBSession.channel, func.count().label("cnt"))
                .group_by(DBSession.channel)
            )).all()
            by_channel = {r.channel: r.cnt for r in channel_rows}

            # ── Sessions by stage ─────────────────────────────────────────────
            stage_rows = (await db.execute(
                select(DBSession.stage, func.count().label("cnt"))
                .group_by(DBSession.stage)
            )).all()
            by_stage = {r.stage: r.cnt for r in stage_rows}

            # ── Need drafts ───────────────────────────────────────────────────
            total_needs = (await db.execute(
                select(func.count()).select_from(NeedDraft)
            )).scalar() or 0

            needs_status_rows = (await db.execute(
                select(NeedDraft.status, func.count().label("cnt"))
                .group_by(NeedDraft.status)
            )).all()
            needs_by_status = {r.status: r.cnt for r in needs_status_rows}

            submitted_needs = needs_by_status.get("submitted", 0)
            draft_needs     = needs_by_status.get("draft", 0)

            # ── Recent sessions (last 50) ─────────────────────────────────────
            recent_rows = (await db.execute(
                select(
                    DBSession.id,
                    DBSession.actor_id,
                    DBSession.channel,
                    DBSession.workflow,
                    DBSession.active_agent,
                    DBSession.persona,
                    DBSession.stage,
                    DBSession.status,
                    DBSession.sub_state,
                    DBSession.volunteer_id,
                    DBSession.channel_metadata,
                    DBSession.created_at,
                    DBSession.last_message_at,
                )
                .order_by(desc(DBSession.updated_at))
                .limit(50)
            )).all()

            recent_sessions = [
                {
                    "id":              str(r.id),
                    "actor_id":        r.actor_id or "unknown",
                    "channel":         r.channel,
                    "workflow":        r.workflow,
                    "active_agent":    r.active_agent,
                    "persona":         r.persona,
                    "stage":           r.stage,
                    "status":          r.status,
                    "sub_state":       r.sub_state,
                    "volunteer_id":    r.volunteer_id,
                    "volunteer_name":  (r.channel_metadata or {}).get("volunteer_name"),
                    "created_at":      r.created_at.isoformat() if r.created_at else None,
                    "last_message_at": r.last_message_at.isoformat() if r.last_message_at else None,
                }
                for r in recent_rows
            ]

            # ── Recent need drafts (last 20) ──────────────────────────────────
            need_rows = (await db.execute(
                select(
                    NeedDraft.id,
                    NeedDraft.session_id,
                    NeedDraft.coordinator_osid,
                    NeedDraft.entity_id,
                    NeedDraft.subjects,
                    NeedDraft.grade_levels,
                    NeedDraft.student_count,
                    NeedDraft.schedule_preference,
                    NeedDraft.status,
                    NeedDraft.created_at,
                    NeedDraft.submitted_at,
                )
                .order_by(desc(NeedDraft.updated_at))
                .limit(20)
            )).all()

            # Fetch sub_state for each session to extract school/coordinator names
            session_ids = [r.session_id for r in need_rows]
            sub_state_map: Dict = {}
            if session_ids:
                from uuid import UUID as _UUID
                sess_rows = (await db.execute(
                    select(DBSession.id, DBSession.sub_state)
                    .where(DBSession.id.in_(session_ids))
                )).all()
                for sr in sess_rows:
                    try:
                        import json as _json
                        ss = _json.loads(sr.sub_state) if sr.sub_state else {}
                        sub_state_map[str(sr.id)] = ss
                    except Exception:
                        sub_state_map[str(sr.id)] = {}

            recent_needs = [
                {
                    "id":                  str(r.id),
                    "session_id":          str(r.session_id),
                    "coordinator_osid":    r.coordinator_osid,
                    "coordinator_name":    sub_state_map.get(str(r.session_id), {}).get("coordinator", {}).get("coordinator_name"),
                    "entity_id":           r.entity_id,
                    "school_name":         sub_state_map.get(str(r.session_id), {}).get("school", {}).get("school_name"),
                    "subjects":            r.subjects or [],
                    "grade_levels":        r.grade_levels or [],
                    "student_count":       r.student_count,
                    "schedule_preference": r.schedule_preference,
                    "status":              r.status,
                    "created_at":          r.created_at.isoformat() if r.created_at else None,
                    "submitted_at":        r.submitted_at.isoformat() if r.submitted_at else None,
                }
                for r in need_rows
            ]

            return {
                "status": "success",
                "stats": {
                    "sessions": {
                        "total":        total_sessions,
                        "active":       active_sessions,
                        "today":        sessions_today,
                        "this_week":    sessions_week,
                        "by_channel":   by_channel,
                        "by_stage":     by_stage,
                    },
                    "needs": {
                        "total":        total_needs,
                        "submitted":    submitted_needs,
                        "draft":        draft_needs,
                        "by_status":    needs_by_status,
                    },
                },
                "recent_sessions": recent_sessions,
                "recent_needs":    recent_needs,
            }

    except Exception as e:
        logger.error(f"Dashboard stats error: {e}")
        return {"status": "error", "error": str(e)}


async def get_conversation_for_session(session_id: str, limit: int = 50) -> Dict[str, Any]:
    """Fetch conversation messages for a session."""
    from services.database import check_db_health
    db_ok = await check_db_health()
    if not db_ok:
        return {"status": "error", "error": "Database not available"}
    try:
        from uuid import UUID
        async with get_db() as db:
            rows = (await db.execute(
                select(
                    ConversationMessage.role,
                    ConversationMessage.content,
                    ConversationMessage.agent,
                    ConversationMessage.created_at,
                )
                .where(ConversationMessage.session_id == UUID(session_id))
                .order_by(ConversationMessage.created_at)
                .limit(limit)
            )).all()
            messages = [
                {
                    "role":       r.role,
                    "content":    r.content,
                    "agent":      r.agent,
                    "timestamp":  r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
            return {"status": "success", "messages": messages}
    except Exception as e:
        logger.error(f"get_conversation error: {e}")
        return {"status": "error", "error": str(e)}


async def get_session_detail(session_id: str) -> Dict[str, Any]:
    """Return full detail for one session: session row, need draft, messages, telemetry."""
    from services.database import check_db_health, TelemetryEvent
    db_ok = await check_db_health()
    if not db_ok:
        return {"status": "error", "error": "Database not available"}
    try:
        from uuid import UUID
        sid = UUID(session_id)
        async with get_db() as db:
            # Session row
            sess_row = (await db.execute(
                select(DBSession).where(DBSession.id == sid)
            )).scalar_one_or_none()
            if not sess_row:
                return {"status": "error", "error": "Session not found"}

            session_data = {
                "id":               str(sess_row.id),
                "actor_id":         sess_row.actor_id,
                "identity_type":    sess_row.identity_type,
                "channel":          sess_row.channel,
                "persona":          sess_row.persona,
                "user_type":        sess_row.user_type,
                "volunteer_id":     sess_row.volunteer_id,
                "coordinator_id":   sess_row.coordinator_id,
                "workflow":         sess_row.workflow,
                "active_agent":     sess_row.active_agent,
                "status":           sess_row.status,
                "stage":            sess_row.stage,
                "sub_state":        sess_row.sub_state,
                "context_summary":  sess_row.context_summary,
                "channel_metadata": sess_row.channel_metadata,
                "last_message_at":  sess_row.last_message_at.isoformat() if sess_row.last_message_at else None,
                "created_at":       sess_row.created_at.isoformat() if sess_row.created_at else None,
                "updated_at":       sess_row.updated_at.isoformat() if sess_row.updated_at else None,
            }

            # Need draft (optional)
            need_row = (await db.execute(
                select(NeedDraft).where(NeedDraft.session_id == sid)
            )).scalar_one_or_none()

            need_data = None
            if need_row:
                need_data = {
                    "id":                   str(need_row.id),
                    "session_id":           str(need_row.session_id),
                    "serve_need_id":        need_row.serve_need_id,
                    "coordinator_osid":     need_row.coordinator_osid,
                    "entity_id":            need_row.entity_id,
                    "subjects":             need_row.subjects or [],
                    "grade_levels":         need_row.grade_levels or [],
                    "student_count":        need_row.student_count,
                    "time_slots":           need_row.time_slots,
                    "start_date":           need_row.start_date,
                    "end_date":             need_row.end_date,
                    "duration_weeks":       need_row.duration_weeks,
                    "schedule_preference":  need_row.schedule_preference,
                    "special_requirements": need_row.special_requirements,
                    "status":               need_row.status,
                    "admin_comments":       need_row.admin_comments,
                    "submitted_at":         need_row.submitted_at.isoformat() if need_row.submitted_at else None,
                    "created_at":           need_row.created_at.isoformat() if need_row.created_at else None,
                    "updated_at":           need_row.updated_at.isoformat() if need_row.updated_at else None,
                }

            # Conversation messages
            msg_rows = (await db.execute(
                select(
                    ConversationMessage.role,
                    ConversationMessage.content,
                    ConversationMessage.agent,
                    ConversationMessage.created_at,
                )
                .where(ConversationMessage.session_id == sid)
                .order_by(ConversationMessage.created_at)
            )).all()
            messages = [
                {
                    "role":      r.role,
                    "content":   r.content,
                    "agent":     r.agent,
                    "timestamp": r.created_at.isoformat() if r.created_at else None,
                }
                for r in msg_rows
            ]

            # Telemetry events (last 50)
            tel_rows = (await db.execute(
                select(
                    TelemetryEvent.event_type,
                    TelemetryEvent.agent,
                    TelemetryEvent.data,
                    TelemetryEvent.timestamp,
                    TelemetryEvent.duration_ms,
                    TelemetryEvent.source_service,
                    TelemetryEvent.domain,
                )
                .where(TelemetryEvent.session_id == sid)
                .order_by(desc(TelemetryEvent.timestamp))
                .limit(50)
            )).all()
            telemetry = [
                {
                    "event_type":     r.event_type,
                    "agent":          r.agent,
                    "source_service": r.source_service,
                    "domain":         r.domain,
                    "data":           r.data,
                    "timestamp":      r.timestamp.isoformat() if r.timestamp else None,
                    "duration_ms":    r.duration_ms,
                }
                for r in tel_rows
            ]

            return {
                "status":    "success",
                "session":   session_data,
                "need_draft": need_data,
                "messages":  messages,
                "telemetry": telemetry,
            }

    except Exception as e:
        logger.error(f"get_session_detail error: {e}")
        return {"status": "error", "error": str(e)}
