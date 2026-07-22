"""API tests via FastAPI TestClient. MCP calls are mocked."""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import main
from app.service import reminder_engine as re_mod


@pytest.fixture
def client():
    return TestClient(main.app)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_tick_idempotency(client, monkeypatch):
    """Two ticks over the same due session should send the reminder exactly once —
    the second tick sees it already sent and skips it."""
    # A tiny fake MCP: tracks which reminder types were 'sent' per session.
    sent_store = {"s1": []}

    fake = AsyncMock()

    async def get_due_reminders(delivery_id=None, now=None):
        return {"status": "success", "candidates": [{
            "delivery_id": "d1", "delivery_status": "active",
            "delivery_session_id": "sess-1", "volunteer_name": "Asha",
            "sent_reminder_types": list(sent_store["s1"]),
            "session": {"id": "s1", "scheduled_date": _today(), "start_time": "23:59",
                        "end_time": "23:59", "subject": "Math", "session_state": "upcoming",
                        "outcome": None},
        }]}

    async def mark_reminder(session_id, reminder_type, status="sent", suppressed_reason=None):
        dup = reminder_type in sent_store[session_id]
        if not dup:
            sent_store[session_id].append(reminder_type)
        return {"status": "success", "duplicate": dup}

    fake.get_due_reminders.side_effect = get_due_reminders
    fake.mark_reminder.side_effect = mark_reminder
    fake.save_message.return_value = {"status": "success"}
    fake.log_event.return_value = {"status": "success"}
    monkeypatch.setattr(re_mod, "domain_client", fake)

    # Force "now" to the morning so the session_day reminder is due.
    body = {"now": f"{_today()}T08:00:00"}
    first = client.post("/api/reminders/tick", json=body).json()
    second = client.post("/api/reminders/tick", json=body).json()

    first_sent = [a for a in first["sent"] if not a["duplicate"]]
    second_sent = [a for a in second["sent"] if not a["duplicate"]]
    assert len(first_sent) == 1          # sent once
    assert len(second_sent) == 0         # not resent
    assert sent_store["s1"] == ["session_day"]


def _today():
    from datetime import date
    return date.today().isoformat()
