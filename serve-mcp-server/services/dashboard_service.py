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

            # ── Recent sessions (last 20) ─────────────────────────────────────
            recent_rows = (await db.execute(
                select(
                    DBSession.id,
                    DBSession.actor_id,
                    DBSession.channel,
                    DBSession.stage,
                    DBSession.status,
                    DBSession.created_at,
                    DBSession.last_message_at,
                )
                .order_by(desc(DBSession.updated_at))
                .limit(20)
            )).all()

            recent_sessions = [
                {
                    "id":              str(r.id),
                    "actor_id":        r.actor_id or "unknown",
                    "channel":         r.channel,
                    "stage":           r.stage,
                    "status":          r.status,
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

            recent_needs = [
                {
                    "id":                  str(r.id),
                    "session_id":          str(r.session_id),
                    "coordinator_osid":    r.coordinator_osid,
                    "entity_id":           r.entity_id,
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
