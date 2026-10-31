"""Meet CUE demo service: API, limits, auth, bot socket, voice loop and summary, with fakes for
Google Calendar, the bot process, speech engines and Claude. Run: .venv/bin/pytest tests/demo -q"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

from cue.demo.app import Demo, create_app
from cue.demo.config import DemoSettings
from cue.demo.google_calendar import GoogleError, Meeting
from cue.demo.store import DemoStore, digest
from cue.demo.voice import GREETING, Endpointer, sentences

KEY = "test-demo-key"


class FakeCalendar:
    def __init__(self, fail=False):
        self.created, self.cancelled, self.fail = [], [], fail

    async def create_meeting(self, **kwargs):
        if self.fail:
            raise GoogleError("boom")
        self.created.append(kwargs)
        return Meeting(event_id=f"evt{len(self.created)}", meet_url="https://meet.google.com/abc-defg-hij", html_link=None)

    async def cancel(self, event_id):
        self.cancelled.append(event_id)


class FakeRunner:
    def __init__(self):
        self.launched, self.stopped = [], []
        self.busy = False

    async def launch(self, session_id, meet_url, bot_key):
        self.launched.append((session_id, meet_url, bot_key))

    async def stop(self, session_id=None, timeout=25):
        self.stopped.append(session_id)


class FakeEngines:
    def __init__(self, text="How do you handle approvals?"):
        self.text = text

    async def transcribe(self, audio):
        return self.text

    async def synthesize(self, text):
        return b"\x01\x00" * 2400, 24000

    def warm(self):
        pass


class FakeBrain:
    def __init__(self):
        self.histories = []

    async def reply(self, history):
        self.histories.append(list(history))
        for piece in ["Risky actions wait ", "for a human. ", "Then I run them."]:
            yield piece

    async def summarize(self, turns):
        return {"summary": "The visitor asked about approvals.", "highlights": [{"speaker": "Visitor", "text": "Asked about approvals."}]}


@pytest.fixture
def make(tmp_path):
    def build(*, calendar=None, voice=True, **overrides):
        settings = replace(DemoSettings(), api_key=KEY, db_path=tmp_path / "demo.sqlite3", **overrides)
        demo = Demo(settings, calendar=calendar or FakeCalendar(), runner=FakeRunner(),
                    engines=FakeEngines() if voice else None, brain=FakeBrain() if voice else None)
        if not voice:
            demo.voice_problem = lambda: "missing ANTHROPIC_API_KEY"
        client = TestClient(create_app(demo, run_scheduler=False))
        client.__enter__()
        client.demo = demo
        return client
    return build


def body(**extra):
    return {"mode": "now", "email": "visitor@example.com", "timezone": "Asia/Kolkata", "consent": True, **extra}


H = {"X-Demo-Key": KEY, "X-Visitor-IP": "203.0.113.7"}


def test_requires_configuration_and_server_key(tmp_path):
    demo = Demo(replace(DemoSettings(), api_key="", db_path=tmp_path / "a.sqlite3"), calendar=FakeCalendar(), runner=FakeRunner())
    with TestClient(create_app(demo, run_scheduler=False)) as client:
        response = client.post("/demo/sessions", json=body(), headers=H)
        assert response.status_code == 503 and response.json()["error"] == "not_configured"


def test_rejects_missing_or_wrong_key(make):
    client = make()
    assert client.post("/demo/sessions", json=body()).status_code == 401
    assert client.post("/demo/sessions", json=body(), headers={"X-Demo-Key": "nope"}).status_code == 401


def test_meet_now_creates_meeting_launches_bot_and_hides_link_without_token(make):
    client = make()
    response = client.post("/demo/sessions", json=body(name="Priya"), headers=H)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["meet_url"] == "https://meet.google.com/abc-defg-hij" and data["token"]
    assert data["status"] == "bot_starting" and data["voice"]["available"] is True
    created = client.demo.calendar.created[0]
    assert created["attendee"] == "visitor@example.com" and "Cue is an AI" in created["description"]
    assert created["summary"] == "Meet Cue with Priya"
    assert client.demo.runner.launched[0][1] == "https://meet.google.com/abc-defg-hij"
    sid = data["session_id"]
    assert client.get(f"/demo/sessions/{sid}", headers=H).status_code == 404
    assert client.get(f"/demo/sessions/{sid}", headers={**H, "Authorization": "Bearer wrong"}).status_code == 404
    status = client.get(f"/demo/sessions/{sid}", headers={**H, "Authorization": f"Bearer {data['token']}"})
    assert status.status_code == 200 and status.json()["meet_url"].startswith("https://meet.google.com/")
    # Only hashes are stored.
    row = client.demo.store.get(sid)
    assert row["token_hash"] == digest(data["token"]) and "visitor@example.com" not in json.dumps(row)


@pytest.mark.parametrize("extra,message", [
    ({"consent": False}, "notice"),
    ({"email": "not-an-email"}, "valid email"),
    ({"timezone": "Mars/Base"}, "timezone"),
    ({"mode": "scheduled"}, "Pick a date"),
    ({"mode": "scheduled", "start_at": (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat()}, "10 minutes"),
    ({"mode": "scheduled", "start_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()}, "days ahead"),
])
def test_validation(make, extra, message):
    response = make().post("/demo/sessions", json=body(**extra), headers=H)
    assert response.status_code == 400 and message in response.json()["message"]


def test_rate_limits_per_ip(make):
    client = make(per_ip_per_hour=2)
    for i in range(2):
        assert client.post("/demo/sessions", json=body(email=f"v{i}@example.com", mode="scheduled",
                           start_at=(datetime.now(timezone.utc) + timedelta(hours=i + 1)).isoformat()), headers=H).status_code == 201
    response = client.post("/demo/sessions", json=body(email="v9@example.com"), headers=H)
    assert response.status_code == 429 and response.json()["retry_after"] >= 60


def test_rate_limits_per_email(make):
    client = make(per_email_per_day=1, per_ip_per_hour=10)
    start = datetime.now(timezone.utc) + timedelta(hours=2)
    assert client.post("/demo/sessions", json=body(mode="scheduled", start_at=start.isoformat()), headers=H).status_code == 201
    response = client.post("/demo/sessions", json=body(mode="scheduled", start_at=(start + timedelta(hours=1)).isoformat()),
                           headers={**H, "X-Visitor-IP": "198.51.100.1"})
    assert response.status_code == 429


def test_one_demo_at_a_time(make):
    client = make()
    start = datetime.now(timezone.utc) + timedelta(hours=3)
    assert client.post("/demo/sessions", json=body(mode="scheduled", start_at=start.isoformat()), headers=H).status_code == 201
    clash = client.post("/demo/sessions", json=body(mode="scheduled", email="b@example.com",
                        start_at=(start + timedelta(minutes=10)).isoformat()), headers=H)
    assert clash.status_code == 409 and clash.json()["error"] == "slot_unavailable"


def test_google_failure_is_reported_not_faked(make):
    client = make(calendar=FakeCalendar(fail=True))
    response = client.post("/demo/sessions", json=body(), headers=H)
    assert response.status_code == 502 and response.json()["error"] == "google_error"
    assert client.demo.runner.launched == []


def test_cancel_scheduled_demo_cancels_invite(make):
    client = make()
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    data = client.post("/demo/sessions", json=body(mode="scheduled", start_at=start.isoformat()), headers=H).json()
    auth = {**H, "Authorization": f"Bearer {data['token']}"}
    assert data["status"] == "scheduled" and client.demo.runner.launched == []
    assert client.post(f"/demo/sessions/{data['session_id']}/cancel", headers=auth).json() == {"status": "cancelled"}
    assert client.demo.calendar.cancelled == ["evt1"]
    assert client.get(f"/demo/sessions/{data['session_id']}", headers=auth).json()["status"] == "cancelled"


def test_scheduler_starts_due_demo_and_ends_overdue(make):
    client = make()
    demo = client.demo
    start = datetime.now(timezone.utc) + timedelta(minutes=11)
    data = client.post("/demo/sessions", json=body(mode="scheduled", start_at=start.isoformat()), headers=H).json()
    sid = data["session_id"]
    demo.store.update(sid, start_at=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat())
    client.portal.call(demo.tick)
    assert demo.runner.launched and demo.store.get(sid)["status"] == "bot_starting"
    demo.store.update(sid, end_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    client.portal.call(demo.tick)
    assert demo.store.get(sid)["status"] == "ended" and sid in demo.runner.stopped


def voiced(ms: int, level=0.3) -> str:
    n = 16 * ms
    tone = (np.sin(np.arange(n) * 2 * np.pi * 220 / 16000) * level * 32767).astype("<i2")
    return base64.b64encode(tone.tobytes()).decode()


def silent(ms: int) -> str:
    return base64.b64encode(np.zeros(16 * ms, dtype="<i2").tobytes()).decode()


def collect(ws, kinds, timeout=5.0):
    found = []
    end = time.time() + timeout
    while time.time() < end:
        message = json.loads(ws.receive_text())
        found.append(message)
        if kinds <= {m["type"] for m in found}:
            return found
    return found


def test_bot_socket_greets_answers_and_barges_in(make):
    client = make()
    data = client.post("/demo/sessions", json=body(), headers=H).json()
    sid, bot_key = data["session_id"], client.demo.runner.launched[0][2]
    with pytest.raises(Exception):
        with client.websocket_connect(f"/demo/bot/{sid}", headers={"Authorization": "Bearer wrong"}) as ws:
            ws.receive_text()
    with client.websocket_connect(f"/demo/bot/{sid}", headers={"Authorization": f"Bearer {bot_key}"}) as ws:
        ws.send_text(json.dumps({"type": "bot_status", "status": "in_call"}))
        greeting = collect(ws, {"speak"})
        speak = next(m for m in greeting if m["type"] == "speak")
        assert speak["text"] == GREETING and speak["format"] == "pcm_s16le" and speak["sample_rate"] == 24000
        auth = {**H, "Authorization": f"Bearer {data['token']}"}
        assert client.get(f"/demo/sessions/{sid}", headers=auth).json()["status"] == "bot_in_call"

        # The visitor asks a question: 600 ms of voice, then silence closes the utterance.
        for chunk in [voiced(200)] * 3 + [silent(200)] * 5:
            ws.send_text(json.dumps({"type": "audio_in", "sample_rate": 16000, "pcm": chunk}))
        reply = collect(ws, {"caption", "speak"}, timeout=8)
        assert {"type": "state", "state": "thinking"} in reply
        assert any(m["type"] == "caption" and m["speaker"] == "You" for m in reply)
        spoken = [m["text"] for m in reply if m["type"] == "speak"]
        assert spoken and spoken[0] == "Risky actions wait for a human."

        # Barge-in: while Cue is speaking, the visitor talks for ~400 ms -> stop.
        ws.send_text(json.dumps({"type": "speak_started", "id": "cue-9"}))
        for chunk in [voiced(200)] * 3:
            ws.send_text(json.dumps({"type": "audio_in", "sample_rate": 16000, "pcm": chunk}))
        assert any(m["type"] == "stop" for m in collect(ws, {"stop"}))

    turns = client.demo.store.turns(sid)
    assert [t["speaker"] for t in turns][:3] == ["Cue", "Visitor", "Cue"]
    history = client.demo.brain.histories[0]
    assert history[-1] == {"role": "user", "content": "How do you handle approvals?"}

    client.portal.call(client.demo.bot_exited, sid, 0, "left the call")
    for _ in range(50):
        summary = client.get(f"/demo/sessions/{sid}/summary", headers=auth).json()
        if summary["status"] == "ready":
            break
        time.sleep(0.05)
    assert summary["status"] == "ready" and summary["highlights"][0]["speaker"] == "Visitor"
    assert client.get(f"/demo/sessions/{sid}", headers=auth).json()["status"] == "ended"


def test_without_voice_the_demo_says_so(make):
    client = make(voice=False)
    data = client.post("/demo/sessions", json=body(), headers=H).json()
    assert data["voice"] == {"available": False, "detail": "missing ANTHROPIC_API_KEY"}
    sid, bot_key = data["session_id"], client.demo.runner.launched[0][2]
    with client.websocket_connect(f"/demo/bot/{sid}", headers={"Authorization": f"Bearer {bot_key}"}) as ws:
        ws.send_text(json.dumps({"type": "bot_status", "status": "in_call"}))
        caption = json.loads(ws.receive_text())
        assert caption["type"] == "caption" and "can't talk" in caption["text"]
    client.portal.call(client.demo.bot_exited, sid, 0, "left the call")
    auth = {**H, "Authorization": f"Bearer {data['token']}"}
    assert client.get(f"/demo/sessions/{sid}/summary", headers=auth).json()["status"] == "unavailable"


def test_failed_join_marks_session_failed(make):
    client = make()
    data = client.post("/demo/sessions", json=body(), headers=H).json()
    client.portal.call(client.demo.bot_exited, data["session_id"], 3, "Cue wasn't admitted to the meeting")
    auth = {**H, "Authorization": f"Bearer {data['token']}"}
    status = client.get(f"/demo/sessions/{data['session_id']}", headers=auth).json()
    assert status["status"] == "failed" and "admitted" in status["error"]


def test_endpointer_and_sentence_splitting():
    vad = Endpointer()
    tone = np.sin(np.arange(16000) * 2 * np.pi * 200 / 16000).astype(np.float32) * 0.3
    assert vad.feed(np.zeros(8000, np.float32)) == []
    assert vad.feed(tone) == [] and vad.in_speech
    done = vad.feed(np.zeros(16000, np.float32))
    assert len(done) == 1 and 1.0 < len(done[0]) / 16000 < 2.1
    ready, rest = sentences("Hello there. How are you? I'm")
    assert ready == ["Hello there.", "How are you?"] and rest == "I'm"


def test_retention_purge(tmp_path):
    store = DemoStore(tmp_path / "s.sqlite3")
    created = store.create(mode="now", email="a@b.co", ip="1.2.3.4", tz="UTC",
                           start_at=datetime.now(timezone.utc), end_at=datetime.now(timezone.utc) + timedelta(minutes=20))
    store.add_turn(created.session["id"], "Visitor", "hi")
    store.db.execute("UPDATE turns SET at = '2000-01-01T00:00:00+00:00'")
    store.db.execute("UPDATE sessions SET created_at = '2000-01-01T00:00:00+00:00'")
    assert store.purge(7, 30) == (1, 1)
