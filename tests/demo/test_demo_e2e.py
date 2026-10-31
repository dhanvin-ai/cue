"""End to end on this machine: demo API -> real face_bot.py process -> fake Meet page -> captured
meeting audio -> faster-whisper -> (fake) Claude -> Kokoro -> Cue speaks in the call -> leave ->
summary. Google Calendar and Claude are faked; everything else is real.

Slow (~1 min, downloads nothing; needs scripts/demo_fetch_models.py run once):
    CUE_DEMO_E2E=1 .venv/bin/pytest tests/demo/test_demo_e2e.py -q -s
"""

from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import threading
import time
import wave
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from cue.demo.app import Demo, create_app
from cue.demo.config import ROOT, DemoSettings
from cue.demo.google_calendar import Meeting
from cue.demo.voice import Engines

pytestmark = pytest.mark.skipif(os.environ.get("CUE_DEMO_E2E") != "1", reason="set CUE_DEMO_E2E=1 to run")

KEY = "e2e-demo-key"
QUESTION = "How do you handle approvals for risky actions?"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_port(port: int, timeout=20) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"nothing listening on {port}")


class CorsHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, *args):
        pass


class Calendar:
    def __init__(self, meet_url):
        self.meet_url = meet_url

    async def create_meeting(self, **kwargs):
        return Meeting(event_id="evt-e2e", meet_url=self.meet_url, html_link=None)

    async def cancel(self, event_id):
        pass


class Brain:
    async def reply(self, history):
        for piece in ["Anything risky waits ", "for a person to approve it. ", "Then I do it."]:
            yield piece

    async def summarize(self, turns):
        asked = next(t["text"] for t in turns if t["speaker"] == "Visitor")
        return {"summary": f"The visitor asked: {asked}", "highlights": []}


@pytest.fixture
def stack(tmp_path):
    import uvicorn

    settings = replace(DemoSettings(), api_key=KEY, db_path=tmp_path / "demo.sqlite3")
    engines = Engines(settings)

    # The participant's question, spoken by Kokoro, served with CORS for fake_meet to fetch.
    pcm, rate = engines.synthesize_sync(QUESTION)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    (tmp_path / "question.wav").write_bytes(buf.getvalue())
    files = ThreadingHTTPServer(("127.0.0.1", 0), partial(CorsHandler, directory=str(tmp_path)))
    threading.Thread(target=files.serve_forever, daemon=True).start()
    wav_url = f"http://127.0.0.1:{files.server_port}/question.wav"

    face_port = free_port()
    face = subprocess.Popen([sys.executable, str(ROOT / "face" / "dev_server.py"), "serve", "--port", str(face_port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_port(face_port)
    meet_url = f"http://127.0.0.1:{face_port}/tests/fake_meet.html?admit_ms=500&say={wav_url}"

    api_port = free_port()
    settings = replace(settings, internal_ws_base=f"ws://127.0.0.1:{api_port}",
                       bot_extra_args=("--guest", "--browser", "chromium", "--headless", "--host-pattern", r"^127\.0\.0\.1$"))
    demo = Demo(settings, calendar=Calendar(meet_url), engines=engines, brain=Brain())
    demo.runner.logs = tmp_path / "logs"
    server = uvicorn.Server(uvicorn.Config(create_app(demo, run_scheduler=True), host="127.0.0.1", port=api_port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    wait_port(api_port)
    yield demo, f"http://127.0.0.1:{api_port}"
    server.should_exit = True
    thread.join(30)
    face.terminate()
    files.shutdown()


def test_meet_cue_now_end_to_end(stack):
    demo, api = stack
    client = httpx.Client(base_url=api, headers={"X-Demo-Key": KEY, "X-Visitor-IP": "198.51.100.20"}, timeout=30)
    created = client.post("/demo/sessions", json={"mode": "now", "email": "e2e@example.com", "timezone": "UTC", "consent": True})
    assert created.status_code == 201, created.text
    data = created.json()
    sid, auth = data["session_id"], {"Authorization": f"Bearer {data['token']}"}
    assert data["voice"]["available"], data

    seen, deadline = [], time.time() + 90
    while time.time() < deadline:
        status = client.get(f"/demo/sessions/{sid}", headers=auth).json()
        if not seen or seen[-1] != status["status"]:
            seen.append(status["status"])
        speakers = [t["speaker"] for t in demo.store.turns(sid)]
        if speakers.count("Cue") >= 2 and "Visitor" in speakers:
            break
        assert status["status"] not in ("failed", "ended"), (status, demo.runner.log_path(sid).read_text())
        time.sleep(0.5)
    log = demo.runner.log_path(sid).read_text()
    turns = demo.store.turns(sid)
    print("\nstatuses:", seen, "\nturns:", [(t["speaker"], t["text"]) for t in turns])
    assert "live" in seen, log
    visitor = next(t["text"] for t in turns if t["speaker"] == "Visitor")
    assert "approv" in visitor.lower(), turns
    assert turns[-1]["speaker"] == "Cue" and "approve" in turns[-1]["text"]

    # The demo's time is up: the scheduler stops the bot, which leaves the call.
    demo.store.update(sid, end_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    deadline = time.time() + 60
    while time.time() < deadline:
        summary = client.get(f"/demo/sessions/{sid}/summary", headers=auth).json()
        if summary["status"] == "ready":
            break
        time.sleep(0.5)
    final = client.get(f"/demo/sessions/{sid}", headers=auth).json()
    log = demo.runner.log_path(sid).read_text()
    assert final["status"] == "ended", final
    assert "Left the call" in log, log
    assert summary["status"] == "ready" and "approv" in summary["summary"].lower(), summary
