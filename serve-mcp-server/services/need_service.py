"""
SERVE MCP Server - Need Service
Need drafts are stored in the MCP DB (need_drafts table) during conversation.
On submission, the draft is pushed to the Serve Need Service via POST /need/raise.
Status updates also propagate to Serve Need Service.
"""
import logging
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select, update

from services.database import NeedDraft, get_db, is_db_healthy
from services.serve_registry_client import need_service_client

logger = logging.getLogger(__name__)

MANDATORY_FIELDS = [
    "subjects", "grade_levels", "student_count",
    "time_slots", "start_date", "duration_weeks",
]

# In-memory fallback
_mem_drafts:   Dict[str, Dict] = {}
_mem_sessions: Dict[str, Dict] = {}
_mem_messages: Dict[str, List] = {}
_mem_events:   Dict[str, List] = {}


class NeedService:

    # ── Session ───────────────────────────────────────────────────────────────

    async def start_session(
        self,
        channel: str,
        whatsapp_number: Optional[str] = None,
        channel_metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Need sessions are created via the main session_service (shared sessions table)."""
        session_id = str(uuid4())
        now = datetime.utcnow().isoformat()
        session = {
            "id": session_id, "channel": channel,
            "workflow": "need_lifecycle", "active_agent": "need",
            "status": "active", "stage": "initiated",
            "whatsapp_number": whatsapp_number,
            "channel_metadata": channel_metadata or {},
            "created_at": now, "updated_at": now,
        }
        _mem_sessions[session_id] = session
        return {"status": "success", "session_id": session_id, "stage": "initiated"}

    async def resume_context(self, session_id: str) -> Dict[str, Any]:
        session = _mem_sessions.get(session_id, {"id": session_id})
        draft   = await self._get_draft(session_id)
        return {
            "status": "success",
            "session": session,
            "need_draft": draft,
        }

    async def advance_state(
        self,
        session_id: str,
        new_state: str,
        sub_state: Optional[str] = None,
    ) -> Dict[str, Any]:
        if session_id in _mem_sessions:
            old = _mem_sessions[session_id].get("stage", "initiated")
            _mem_sessions[session_id]["stage"]     = new_state
            _mem_sessions[session_id]["sub_state"] = sub_state
            _mem_sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()
            return {"status": "success", "previous_state": old, "current_state": new_state}
        return {"status": "success", "current_state": new_state}

    async def pause_session(
        self,
        session_id: str,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        if session_id in _mem_sessions:
            _mem_sessions[session_id]["status"] = "paused"
        return {"status": "success", "paused": True, "reason": reason}

    # ── Need Draft (MCP DB) ───────────────────────────────────────────────────

    async def save_need_draft(
        self,
        session_id: str,
        need_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Save or update the working need draft in MCP DB."""
        now = datetime.utcnow()

        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(NeedDraft).where(
                            NeedDraft.session_id == UUID(session_id)
                        )
                    )
                    existing = result.scalar_one_or_none()

                    update_values: Dict[str, Any] = {"updated_at": now}
                    allowed = {
                        "subjects", "grade_levels", "student_count",
                        "time_slots", "start_date", "end_date", "duration_weeks",
                        "schedule_preference", "special_requirements",
                        "coordinator_osid", "entity_id", "status",
                    }
                    for k, v in need_data.items():
                        if k in allowed and v is not None:
                            update_values[k] = v

                    # Auto-compute end_date from start_date + duration_weeks
                    if "start_date" in update_values and "duration_weeks" in update_values:
                        try:
                            sd = date.fromisoformat(update_values["start_date"])
                            ed = sd + timedelta(weeks=int(update_values["duration_weeks"]))
                            update_values["end_date"] = ed.isoformat()
                        except Exception:
                            pass

                    if existing:
                        await db.execute(
                            update(NeedDraft)
                            .where(NeedDraft.session_id == UUID(session_id))
                            .values(**update_values)
                        )
                        draft_id = str(existing.id)
                    else:
                        update_values["session_id"] = UUID(session_id)
                        update_values["created_at"] = now
                        update_values.setdefault("status", "draft")
                        new_draft = NeedDraft(**update_values)
                        db.add(new_draft)
                        draft_id = str(new_draft.id)

                logger.info(f"Need draft saved in MCP DB for session {session_id[:8]}…")
                return {"status": "success", "need_id": draft_id, "draft": need_data}
            except Exception as e:
                logger.warning(f"DB save_need_draft failed: {e}")

        # In-memory fallback
        if session_id not in _mem_drafts:
            _mem_drafts[session_id] = {"id": str(uuid4()), "session_id": session_id,
                                        "status": "draft", "created_at": now.isoformat()}
        _mem_drafts[session_id].update(need_data)
        _mem_drafts[session_id]["updated_at"] = now.isoformat()
        return {"status": "success",
                "need_id": _mem_drafts[session_id]["id"],
                "draft": _mem_drafts[session_id]}

    async def get_missing_fields(self, session_id: str) -> Dict[str, Any]:
        draft = await self._get_draft(session_id)
        missing   = []
        confirmed = {}
        for f in MANDATORY_FIELDS:
            val = draft.get(f)
            if not val or (isinstance(val, list) and len(val) == 0):
                missing.append(f)
            else:
                confirmed[f] = val

        total      = len(MANDATORY_FIELDS)
        completion = round(((total - len(missing)) / total) * 100) if total else 0
        return {
            "status":                "success",
            "missing_fields":        missing,
            "confirmed_fields":      confirmed,
            "completion_percentage": completion,
        }

    async def evaluate_readiness(self, session_id: str) -> Dict[str, Any]:
        result  = await self.get_missing_fields(session_id)
        missing = result.get("missing_fields", [])
        is_ready = len(missing) == 0
        return {
            "status":         "success",
            "is_ready":       is_ready,
            "missing_fields": missing,
            "warnings":       [],
            "completion_percentage": result.get("completion_percentage", 0),
            "recommendation": "submit_need" if is_ready else "continue_drafting",
        }

    # ── Submit to Serve Need Service ──────────────────────────────────────────

    async def submit_for_approval(self, need_id: str) -> Dict[str, Any]:
        """
        Find the draft by need_id (or session context) and push it
        to the Serve Need Service via POST /need/raise.
        """
        # Find draft
        draft = await self._get_draft_by_need_id(need_id)
        if not draft:
            return {"status": "error", "error_message": f"Draft {need_id} not found"}

        coordinator_osid = draft.get("coordinator_osid")
        entity_id        = draft.get("entity_id")

        if not coordinator_osid or not entity_id:
            return {
                "status": "error",
                "error_message": "coordinator_osid and entity_id must be set before submission",
            }

        result = await need_service_client.raise_need(
            coordinator_osid=coordinator_osid,
            entity_id=entity_id,
            need_draft=draft,
        )

        if result and result.get("id"):
            serve_need_id = str(result["id"])
            await self._mark_submitted(need_id, serve_need_id)
            logger.info(f"Need submitted to Serve Need Service: {serve_need_id}")
            return {
                "status":       "success",
                "serve_need_id": serve_need_id,
                "need":          result,
            }

        return {"status": "error", "error_message": "Serve Need Service submission failed"}

    async def update_status(
        self,
        need_id: str,
        status: str,
        comments: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update need status in both MCP DB draft and Serve Need Service."""
        # Update in MCP DB
        await self._update_draft_status(need_id, status, comments)

        # If we have a serve_need_id, also update in Serve Need Service
        draft = await self._get_draft_by_need_id(need_id)
        serve_need_id = draft.get("serve_need_id") if draft else None
        if serve_need_id:
            result = await need_service_client.update_need_status(serve_need_id, status)
            logger.info(f"Need status updated in Serve Need Service: {serve_need_id} → {status}")
            return {"status": "success", "serve_need_id": serve_need_id, "new_status": status}

        return {"status": "success", "need_id": need_id, "new_status": status}

    async def prepare_fulfillment_handoff(self, need_id: str) -> Dict[str, Any]:
        """Assemble fulfillment handoff payload from MCP DB + Serve Need Service."""
        draft = await self._get_draft_by_need_id(need_id)
        if not draft:
            return {"status": "error", "error_message": f"Draft {need_id} not found"}

        serve_need_id = draft.get("serve_need_id")
        serve_need    = None
        if serve_need_id:
            serve_need = await need_service_client.get_need(serve_need_id)

        entity = None
        if draft.get("entity_id"):
            entity = await need_service_client.get_entity(draft["entity_id"])

        return {
            "status":             "success",
            "need_id":            need_id,
            "serve_need_id":      serve_need_id,
            "need_details":       serve_need or draft,
            "school":             entity,
            "coordinator_osid":   draft.get("coordinator_osid"),
            "approval_status":    draft.get("status", "draft"),
            "priority":           "normal",
        }

    # ── Messages & Events ─────────────────────────────────────────────────────

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        msg_id = str(uuid4())
        if session_id not in _mem_messages:
            _mem_messages[session_id] = []
        _mem_messages[session_id].append({
            "id": msg_id, "role": role, "content": content,
            "agent": agent, "timestamp": datetime.utcnow().isoformat(),
        })
        return {"status": "success", "message_id": msg_id}

    async def log_event(
        self,
        session_id: str,
        event_type: str,
        data: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        event_id = str(uuid4())
        if session_id not in _mem_events:
            _mem_events[session_id] = []
        _mem_events[session_id].append({
            "id": event_id, "event_type": event_type,
            "data": data or {}, "timestamp": datetime.utcnow().isoformat(),
        })
        return {"status": "success", "event_id": event_id}

    async def emit_handoff_event(
        self,
        session_id: str,
        from_agent: str,
        to_agent: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        return await self.log_event(
            session_id,
            "handoff",
            data={"from": from_agent, "to": to_agent, "payload": payload},
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_draft(self, session_id: str) -> Dict:
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(NeedDraft).where(
                            NeedDraft.session_id == UUID(session_id)
                        )
                    )
                    row = result.scalar_one_or_none()
                    if row:
                        return self._row_to_dict(row)
            except Exception as e:
                logger.warning(f"DB _get_draft failed: {e}")
        return _mem_drafts.get(session_id, {})

    async def _get_draft_by_need_id(self, need_id: str) -> Optional[Dict]:
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(NeedDraft).where(NeedDraft.id == UUID(need_id))
                    )
                    row = result.scalar_one_or_none()
                    if row:
                        return self._row_to_dict(row)
            except Exception as e:
                logger.warning(f"DB _get_draft_by_need_id failed: {e}")
        for draft in _mem_drafts.values():
            if draft.get("id") == need_id:
                return draft
        return None

    async def _mark_submitted(self, draft_id: str, serve_need_id: str) -> None:
        now = datetime.utcnow()
        if is_db_healthy():
            try:
                async with get_db() as db:
                    await db.execute(
                        update(NeedDraft)
                        .where(NeedDraft.id == UUID(draft_id))
                        .values(
                            serve_need_id=serve_need_id,
                            status="submitted",
                            submitted_at=now,
                            updated_at=now,
                        )
                    )
                return
            except Exception as e:
                logger.warning(f"DB _mark_submitted failed: {e}")
        for draft in _mem_drafts.values():
            if draft.get("id") == draft_id:
                draft["serve_need_id"] = serve_need_id
                draft["status"]        = "submitted"
                draft["submitted_at"]  = now.isoformat()

    async def _update_draft_status(
        self, need_id: str, status: str, comments: Optional[str]
    ) -> None:
        now = datetime.utcnow()
        if is_db_healthy():
            try:
                async with get_db() as db:
                    await db.execute(
                        update(NeedDraft)
                        .where(NeedDraft.id == UUID(need_id))
                        .values(
                            status=status,
                            admin_comments=comments,
                            updated_at=now,
                        )
                    )
                return
            except Exception as e:
                logger.warning(f"DB _update_draft_status failed: {e}")

    def _row_to_dict(self, row: NeedDraft) -> Dict:
        return {
            "id":                   str(row.id),
            "session_id":           str(row.session_id),
            "serve_need_id":        row.serve_need_id,
            "coordinator_osid":     row.coordinator_osid,
            "entity_id":            row.entity_id,
            "subjects":             row.subjects or [],
            "grade_levels":         row.grade_levels or [],
            "student_count":        row.student_count,
            "time_slots":           row.time_slots or [],
            "start_date":           row.start_date,
            "end_date":             row.end_date,
            "duration_weeks":       row.duration_weeks,
            "schedule_preference":  row.schedule_preference,
            "special_requirements": row.special_requirements,
            "status":               row.status,
            "admin_comments":       row.admin_comments,
            "submitted_at":         row.submitted_at.isoformat() if row.submitted_at else None,
            "created_at":           row.created_at.isoformat() if row.created_at else None,
            "updated_at":           row.updated_at.isoformat() if row.updated_at else None,
        }


need_service = NeedService()
