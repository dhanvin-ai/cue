"""Launches and supervises scripts/face_bot.py for demo sessions.

One bot at a time: the bot uses Cue's single signed-in Chrome profile. The bot connects back to
this service's WebSocket with a per-session key passed in its environment (never on the command
line, so it doesn't show up in `ps`).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from cue.demo.config import HOME, ROOT, DemoSettings

log = logging.getLogger("cue.demo.bot")

EXIT_REASONS = {
    0: "left the call",
    2: "bot configuration error (is Cue's Chrome profile in use?)",
    3: "Cue wasn't admitted to the meeting",
    4: "Cue couldn't join the meeting",
    130: "bot was stopped",
}


class Busy(RuntimeError):
    pass


@dataclass
class Running:
    session_id: str
    process: asyncio.subprocess.Process
    watcher: asyncio.Task


class BotRunner:
    def __init__(self, settings: DemoSettings, on_exit: Callable[[str, int, str], Awaitable[None]]):
        self.settings = settings
        self.on_exit = on_exit
        self.current: Running | None = None
        self.logs = HOME / "logs"

    @property
    def busy(self) -> bool:
        return self.current is not None and self.current.process.returncode is None

    def command(self, session_id: str, meet_url: str) -> list[str]:
        s = self.settings
        return [
            sys.executable, str(ROOT / "scripts" / "face_bot.py"), "join", meet_url,
            "--ws", f"{s.internal_ws_base}/demo/bot/{session_id}",
            "--profile", str(s.bot_profile),
            "--capture-audio",
            "--auto-admit", str(s.bot_auto_admit),
            "--max-minutes", str(s.session_minutes + 2),
            "--wait-for-guest", "600",
            "--alone-timeout", "60",
            "-v",
            *s.bot_extra_args,
        ]

    async def launch(self, session_id: str, meet_url: str, bot_key: str) -> None:
        if self.busy:
            raise Busy("Cue is already in another demo")
        self.logs.mkdir(parents=True, exist_ok=True)
        log_file = (self.logs / f"{session_id}.log").open("ab")
        env = {**os.environ, "CUE_FACE_WS_TOKEN": bot_key, "PYTHONUNBUFFERED": "1"}
        process = await asyncio.create_subprocess_exec(
            *self.command(session_id, meet_url), stdout=log_file, stderr=asyncio.subprocess.STDOUT,
            env=env, cwd=str(ROOT), start_new_session=True,
        )
        log_file.close()
        log.info("[%s] bot started (pid %s)", session_id, process.pid)
        self.current = Running(session_id, process, asyncio.create_task(self._watch(session_id, process)))

    async def _watch(self, session_id: str, process: asyncio.subprocess.Process) -> None:
        code = await process.wait()
        log.info("[%s] bot exited with %s", session_id, code)
        if self.current and self.current.process is process:
            self.current = None
        await self.on_exit(session_id, code, EXIT_REASONS.get(code, f"bot exited unexpectedly ({code})"))

    async def stop(self, session_id: str | None = None, timeout: float = 25) -> None:
        """SIGTERM lets the bot stop speech and click Leave call; SIGKILL only as a last resort."""
        running = self.current
        if not running or (session_id and running.session_id != session_id) or running.process.returncode is not None:
            return
        running.process.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(asyncio.shield(running.watcher), timeout)
        except TimeoutError:
            log.warning("[%s] bot ignored SIGTERM; killing it", running.session_id)
            running.process.kill()

    def log_path(self, session_id: str) -> Path:
        return self.logs / f"{session_id}.log"
