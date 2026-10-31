"""Meet CUE demo API. Run separately from the tenant API:

    uvicorn cue.demo.app:app --host 127.0.0.1 --port 8780

Only the website's server calls this (shared X-Demo-Key); visitors hold a per-session token in an
httpOnly cookie that the website forwards as a Bearer token. The face bot connects to
/demo/bot/{id} with a per-session bot key. No tenant database, connector or memory is touched.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from cue.demo.config import DemoSettings, settings as default_settings
from cue.demo.google_calendar import Calendar, GoogleCalendar, GoogleError
from cue.demo.orchestrator import BotRunner, Busy
from cue.demo.store import TERMINAL, DemoStore, iso, now, parse
from cue.demo.voice import Brain, Engines, VoiceAgent

log = logging.getLogger("cue.demo")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
BOT_STATUS = {
    "joining": "bot_joining",
    "waiting_admission": "bot_waiting",
    "in_call": "bot_in_call",
    "video_live": "live",
    "video_full_resolution": "live",
}


class CreateBody(BaseModel):
    mode: Literal["now", "scheduled"]
    email: str = Field(max_length=320)
    name: str | None = Field(default=None, max_length=80)
    start_at: datetime | None = None
    timezone: str = Field(default="UTC", max_length=64)
    consent: bool


def error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse({"error": code, "message": message, **extra}, status_code=status)


class Demo:
    """Everything the app needs, built once; tests inject fakes."""

    def __init__(self, settings: DemoSettings, *, calendar: Calendar | None = None, engines: Engines | None = None,
                 brain: Brain | None = None, runner: BotRunner | None = None):
        self.settings = settings
        self.store = DemoStore(settings.db_path, pepper=settings.api_key)
        self.calendar = calendar
        self.engines = engines
        self.brain = brain
        self.runner = runner or BotRunner(settings, self.bot_exited)
        self.agents: dict[str, VoiceAgent] = {}
        self.summarizing: set[str] = set()
        self.tasks: set[asyncio.Task] = set()

    def calendar_client(self) -> Calendar:
        if self.calendar is None:
            self.calendar = GoogleCalendar(self.settings.google_token_file, self.settings.calendar_id)
        return self.calendar

    def voice_problem(self) -> str | None:
        if self.engines is not None and self.brain is not None:
            return None
        missing = self.settings.voice_missing()
        if missing:
            return "missing " + ", ".join(missing)
        try:
            self.engines = self.engines or Engines(self.settings)
            self.brain = self.brain or Brain(self.settings.model)
            self.engines.warm()
        except Exception as exc:  # noqa: BLE001 - report, don't crash the API
            return f"voice pipeline failed to start: {exc.__class__.__name__}"
        return None

    def spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    # -- lifecycle ------------------------------------------------------------------------------

    async def start_bot(self, session_id: str) -> None:
        session = self.store.get(session_id)
        if not session or session["status"] in TERMINAL or not session["meet_url"]:
            return
        if not self.settings.bot_enabled:
            self.store.set_status(session_id, "failed", error="The meeting bot is disabled on this server (CUE_DEMO_BOT=0).")
            return
        bot_key = self.store.rotate_bot_key(session_id)
        try:
            await self.runner.launch(session_id, session["meet_url"], bot_key)
        except Busy as exc:
            self.store.set_status(session_id, "failed", error=str(exc))
            return
        except OSError as exc:
            self.store.set_status(session_id, "failed", error=f"Could not start the meeting bot: {exc}")
            return
        self.store.set_status(session_id, "bot_starting", bot_status="starting")

    async def bot_exited(self, session_id: str, code: int, reason: str) -> None:
        session = self.store.get(session_id)
        agent = self.agents.pop(session_id, None)
        if agent:
            await agent.close()
        if not session:
            return
        joined = bool(session["joined_at"])
        if session["status"] not in TERMINAL:
            if joined or code in (0, 130):
                self.store.update(session_id, status="ended", ended_at=iso(now()), bot_status="left", bot_detail=reason)
            else:
                self.store.update(session_id, status="failed", error=reason, bot_status="exited", bot_detail=reason)
        self.spawn(self.summarize(session_id))

    async def summarize(self, session_id: str) -> None:
        turns = self.store.turns(session_id)
        if not self.brain or not any(t["speaker"] == "Visitor" for t in turns) or self.store.summary(session_id):
            return
        self.summarizing.add(session_id)
        try:
            result = await self.brain.summarize(turns)
            self.store.set_summary(session_id, {
                "summary": result.get("summary", ""),
                "highlights": result.get("highlights", [])[:5],
            })
        except Exception:  # noqa: BLE001 - summary is best effort
            log.exception("[%s] summary failed", session_id)
            self.store.set_summary(session_id, {"error": "The summary couldn't be generated."})
        finally:
            self.summarizing.discard(session_id)

    async def tick(self) -> None:
        """Start due scheduled sessions, end overdue ones, purge old data."""
        for session in self.store.due_to_start(timedelta(seconds=60)):
            if self.runner.busy:
                continue  # the overlap check makes this rare; retry on the next tick
            self.store.set_status(session["id"], "bot_starting")
            await self.start_bot(session["id"])
        for session in self.store.overdue():
            if session["status"] == "scheduled":
                self.store.update(session["id"], status="failed", error="Cue couldn't start this demo in time.")
            else:
                await self.runner.stop(session["id"])
                self.store.set_status(session["id"], "ended", ended_at=iso(now()), bot_detail="time limit reached")

    async def scheduler(self) -> None:
        last_purge = None
        while True:
            try:
                await self.tick()
                if last_purge is None or now() - last_purge > timedelta(hours=6):
                    self.store.purge(self.settings.transcript_retention_days, self.settings.session_retention_days)
                    last_purge = now()
            except Exception:  # noqa: BLE001 - keep scheduling
                log.exception("scheduler tick failed")
            await asyncio.sleep(10)

    # -- presentation ---------------------------------------------------------------------------

    def present(self, session: dict) -> dict:
        problem = session["voice_detail"]
        return {
            "session_id": session["id"],
            "mode": session["mode"],
            "status": session["status"],
            "meet_url": session["meet_url"],
            "start_at": session["start_at"],
            "end_at": session["end_at"],
            "error": session["error"],
            "bot": {"status": session["bot_status"], "detail": session["bot_detail"]},
            "voice": {"available": problem is None, "detail": problem},
            "summary_ready": bool(session["summary"]),
        }


def create_app(demo: Demo | None = None, *, run_scheduler: bool = True) -> FastAPI:
    holder: dict[str, Demo] = {}

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        holder["demo"] = demo or Demo(default_settings)
        task = asyncio.create_task(holder["demo"].scheduler()) if run_scheduler else None
        yield
        if task:
            task.cancel()
        await holder["demo"].runner.stop()

    app = FastAPI(title="Cue demo", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def get() -> Demo:
        return holder["demo"]

    def server_key_ok(key: str | None) -> bool:
        expected = get().settings.api_key
        return bool(expected) and bool(key) and hmac.compare_digest(key, expected)

    def visitor(session_id: str, authorization: str | None) -> dict | None:
        if not UUID.match(session_id) or not authorization or not authorization.startswith("Bearer "):
            return None
        return get().store.authorized(session_id, authorization[7:])

    @app.get("/demo/health")
    async def health(x_demo_key: str | None = Header(default=None)):
        if not server_key_ok(x_demo_key):
            return error(401, "unauthorized", "Missing or wrong X-Demo-Key")
        d = get()
        return {"meetings": {"missing": d.settings.missing()}, "voice": {"missing": d.settings.voice_missing()},
                "bot": {"enabled": d.settings.bot_enabled, "busy": d.runner.busy}}

    @app.post("/demo/sessions", status_code=201)
    async def create(body: CreateBody, request: Request, x_demo_key: str | None = Header(default=None),
                     x_visitor_ip: str | None = Header(default=None)):
        d = get()
        if not d.settings.api_key:
            return error(503, "not_configured", "Live demos aren't configured on this server.", missing=["CUE_DEMO_API_KEY"])
        if not server_key_ok(x_demo_key):
            return error(401, "unauthorized", "Missing or wrong X-Demo-Key")
        missing = [m for m in d.settings.missing() if m != "CUE_DEMO_API_KEY"] if d.calendar is None else []
        if missing:
            return error(503, "not_configured", "Live demos aren't available right now.", missing=missing)
        if not body.consent:
            return error(400, "invalid", "Please accept the AI and transcription notice to continue.")
        email = body.email.strip()
        if not EMAIL.match(email):
            return error(400, "invalid", "Enter a valid email address for the calendar invite.")
        try:
            zone = ZoneInfo(body.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return error(400, "invalid", "Unknown timezone.")
        minutes = timedelta(minutes=d.settings.session_minutes)
        if body.mode == "now":
            start = now()
        else:
            if body.start_at is None or body.start_at.tzinfo is None:
                return error(400, "invalid", "Pick a date and time for the demo.")
            start = body.start_at
            if start < now() + timedelta(minutes=10) - timedelta(seconds=30):
                return error(400, "invalid", "Schedule the demo at least 10 minutes from now.")
            if start > now() + timedelta(days=d.settings.max_schedule_days):
                return error(400, "invalid", f"Demos can be booked up to {d.settings.max_schedule_days} days ahead.")
        end = start + minutes

        ip = (x_visitor_ip or (request.client.host if request.client else "unknown")).split(",")[0].strip()
        checks = (
            ("ip_hash", ip, timedelta(hours=1), d.settings.per_ip_per_hour, "Too many demos from your network. Try again later."),
            ("email_hash", email, timedelta(days=1), d.settings.per_email_per_day, "This email has booked the maximum demos for today."),
        )
        for column, value, window, limit, message in checks:
            since = now() - window
            if d.store.count_since(column, value, since) >= limit:
                oldest = d.store.oldest_since(column, value, since) or now()
                retry = max(60, int((oldest + window - now()).total_seconds()))
                return error(429, "rate_limited", message, retry_after=retry)
        if d.store.count_total_since(now() - timedelta(days=1)) >= d.settings.per_day_total:
            return error(429, "rate_limited", "Live demos are fully booked today. Please schedule one for later.", retry_after=3600)
        if d.store.overlapping(start, end) or (body.mode == "now" and d.runner.busy):
            return error(409, "slot_unavailable", "Cue is in another demo at that time. Pick another slot or try again in a few minutes.")

        created = d.store.create(mode=body.mode, email=email, ip=ip, tz=body.timezone, start_at=start, end_at=end)
        session_id = created.session["id"]
        problem = d.voice_problem()
        if problem:
            d.store.update(session_id, voice_detail=problem)
        local = start.astimezone(zone)
        description = (
            "A live demo call with Cue, the AI teammate.\n\n"
            "Cue is an AI, not a person. The call is transcribed and processed by AI so Cue can answer you "
            f"and send a short summary afterwards; transcripts are deleted after {d.settings.transcript_retention_days} days. "
            "Please don't share confidential information. This demo isn't connected to any company's data.\n\n"
            f"Session page and summary: {d.settings.public_url}/meet-cue/session/{session_id}\n"
            f"The call ends automatically after {d.settings.session_minutes} minutes."
        )
        try:
            meeting = await d.calendar_client().create_meeting(
                summary=f"Meet Cue{' with ' + body.name.strip() if body.name and body.name.strip() else ''}",
                description=description, start=start.isoformat(), end=end.isoformat(),
                attendee=email, request_id=session_id,
            )
        except GoogleError as exc:
            log.warning("[%s] calendar error: %s", session_id, exc)
            d.store.update(session_id, status="failed", error="Google Calendar couldn't create the meeting.")
            return error(502, "google_error", "We couldn't create the Google Meet. Please try again shortly.")
        d.store.update(session_id, meet_url=meeting.meet_url, event_id=meeting.event_id)
        log.info("[%s] %s demo created for %s", session_id, body.mode, local.isoformat())
        if body.mode == "now":
            d.store.set_status(session_id, "bot_starting", bot_status="starting")
            d.spawn(d.start_bot(session_id))
        payload = d.present(d.store.get(session_id))
        return {**payload, "token": created.token}

    @app.get("/demo/sessions/{session_id}")
    async def status(session_id: str, x_demo_key: str | None = Header(default=None),
                     authorization: str | None = Header(default=None)):
        if not server_key_ok(x_demo_key):
            return error(401, "unauthorized", "Missing or wrong X-Demo-Key")
        session = visitor(session_id, authorization)
        if not session:
            return error(404, "not_found", "Demo session not found.")
        return get().present(session)

    @app.get("/demo/sessions/{session_id}/summary")
    async def summary(session_id: str, x_demo_key: str | None = Header(default=None),
                      authorization: str | None = Header(default=None)):
        if not server_key_ok(x_demo_key):
            return error(401, "unauthorized", "Missing or wrong X-Demo-Key")
        session = visitor(session_id, authorization)
        if not session:
            return error(404, "not_found", "Demo session not found.")
        d = get()
        joined, ended = parse(session["joined_at"]), parse(session["ended_at"])
        duration = int((ended - joined).total_seconds()) if joined and ended else None
        result = {"status": "pending", "summary": None, "highlights": [], "duration_seconds": duration, "detail": None}
        if session["status"] not in TERMINAL or session_id in d.summarizing:
            return result
        stored = d.store.summary(session_id)
        if stored and not stored.get("error"):
            return {**result, "status": "ready", "summary": stored["summary"], "highlights": stored["highlights"]}
        if stored and stored.get("error"):
            return {**result, "status": "unavailable", "detail": stored["error"]}
        if session["voice_detail"]:
            return {**result, "status": "unavailable", "detail": "Cue's voice pipeline wasn't available, so there was no conversation to summarize."}
        if not any(t["speaker"] == "Visitor" for t in d.store.turns(session_id)):
            return {**result, "status": "unavailable", "detail": "No conversation was recorded in this call."}
        d.spawn(d.summarize(session_id))
        return result

    @app.post("/demo/sessions/{session_id}/cancel")
    async def cancel(session_id: str, x_demo_key: str | None = Header(default=None),
                     authorization: str | None = Header(default=None)):
        if not server_key_ok(x_demo_key):
            return error(401, "unauthorized", "Missing or wrong X-Demo-Key")
        session = visitor(session_id, authorization)
        if not session:
            return error(404, "not_found", "Demo session not found.")
        d = get()
        if session["status"] in TERMINAL:
            return {"status": session["status"]}
        d.store.update(session_id, status="cancelled", ended_at=iso(now()))
        await d.runner.stop(session_id)
        if session["event_id"] and parse(session["start_at"]) > now():
            try:
                await d.calendar_client().cancel(session["event_id"])
            except GoogleError as exc:
                log.warning("[%s] could not cancel the calendar event: %s", session_id, exc)
        return {"status": "cancelled"}

    @app.websocket("/demo/bot/{session_id}")
    async def bot_socket(websocket: WebSocket, session_id: str):
        d = get()
        auth = websocket.headers.get("authorization", "")
        session = d.store.bot_authorized(session_id, auth[7:]) if UUID.match(session_id) and auth.startswith("Bearer ") else None
        if not session or session["status"] in TERMINAL:
            await websocket.close(code=4401)
            return
        await websocket.accept()

        async def send(message: dict) -> None:
            await websocket.send_text(json.dumps(message))

        agent = d.agents.get(session_id)
        if agent is None:
            agent = VoiceAgent(
                session_id, send, engines=d.engines, brain=d.brain,
                on_turn=lambda speaker, text: d.store.add_turn(session_id, speaker, text),
                unavailable=session["voice_detail"],
            )
            d.agents[session_id] = agent
        else:
            agent.send = send  # the bot reconnected
        try:
            while True:
                message = json.loads(await websocket.receive_text())
                kind = message.get("type")
                if kind == "bot_status":
                    status = message.get("status")
                    mapped = BOT_STATUS.get(status)
                    fields = {"bot_status": status, "bot_detail": message.get("detail")}
                    if mapped:
                        if mapped in ("bot_in_call", "live") and not d.store.get(session_id)["joined_at"]:
                            fields["joined_at"] = iso(now())
                        d.store.set_status(session_id, mapped, **fields)
                    else:
                        d.store.update(session_id, **fields)
                    if status in ("in_call", "video_live"):
                        await agent.joined()
                else:
                    await agent.handle(message)
        except (WebSocketDisconnect, RuntimeError):
            pass
        except json.JSONDecodeError:
            await websocket.close(code=4400)

    app.state.demo = holder
    return app


app = create_app()
