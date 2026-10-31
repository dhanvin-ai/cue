"""SQLite store for demo sessions. Deliberately separate from the tenant Postgres database.

Only what the demo needs is kept: hashed visitor email and IP (for rate limits), the Meet URL,
status, a short transcript (deleted after `transcript_retention_days`) and the summary.
Session tokens are stored as SHA-256 hashes; the raw token only ever goes to the visitor's cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

TERMINAL = {"ended", "failed", "cancelled"}
ACTIVE = {"creating", "bot_starting", "bot_joining", "bot_waiting", "bot_in_call", "live"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL,
  bot_key_hash TEXT NOT NULL,
  mode TEXT NOT NULL,
  status TEXT NOT NULL,
  email_hash TEXT NOT NULL,
  ip_hash TEXT NOT NULL,
  timezone TEXT,
  meet_url TEXT,
  event_id TEXT,
  start_at TEXT NOT NULL,
  end_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  bot_status TEXT,
  bot_detail TEXT,
  error TEXT,
  voice_detail TEXT,
  joined_at TEXT,
  ended_at TEXT,
  summary TEXT
);
CREATE INDEX IF NOT EXISTS sessions_start ON sessions (start_at);
CREATE TABLE IF NOT EXISTS turns (
  session_id TEXT NOT NULL,
  at TEXT NOT NULL,
  speaker TEXT NOT NULL,
  text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS turns_session ON turns (session_id);
"""


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def digest(value: str, pepper: str = "") -> str:
    return hashlib.sha256((pepper + value.strip().lower()).encode()).hexdigest()


@dataclass
class Created:
    session: dict
    token: str
    bot_key: str


class DemoStore:
    def __init__(self, path: Path, pepper: str = ""):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.pepper = pepper
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def _one(self, sql: str, args: tuple = ()) -> dict | None:
        with self.lock:
            row = self.db.execute(sql, args).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.db.execute(sql, args).fetchall()]

    def _exec(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            return self.db.execute(sql, args).rowcount

    # -- sessions -------------------------------------------------------------------------------

    def create(self, *, mode: str, email: str, ip: str, tz: str | None, start_at: datetime, end_at: datetime) -> Created:
        token = secrets.token_urlsafe(32)
        bot_key = secrets.token_urlsafe(32)
        session_id = str(uuid4())
        stamp = iso(now())
        status = "creating" if mode == "now" else "scheduled"
        self._exec(
            "INSERT INTO sessions (id, token_hash, bot_key_hash, mode, status, email_hash, ip_hash, timezone,"
            " start_at, end_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (session_id, digest(token), digest(bot_key), mode, status, digest(email, self.pepper), digest(ip, self.pepper),
             tz, iso(start_at), iso(end_at), stamp, stamp),
        )
        return Created(self.get(session_id), token, bot_key)

    def get(self, session_id: str) -> dict | None:
        return self._one("SELECT * FROM sessions WHERE id = ?", (session_id,))

    def authorized(self, session_id: str, token: str) -> dict | None:
        session = self.get(session_id)
        if session and hmac.compare_digest(session["token_hash"], digest(token)):
            return session
        return None

    def bot_authorized(self, session_id: str, bot_key: str) -> dict | None:
        session = self.get(session_id)
        if session and hmac.compare_digest(session["bot_key_hash"], digest(bot_key)):
            return session
        return None

    def rotate_bot_key(self, session_id: str) -> str:
        bot_key = secrets.token_urlsafe(32)
        self._exec("UPDATE sessions SET bot_key_hash = ? WHERE id = ?", (digest(bot_key), session_id))
        return bot_key

    def update(self, session_id: str, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = iso(now())
        columns = ", ".join(f"{key} = ?" for key in fields)
        self._exec(f"UPDATE sessions SET {columns} WHERE id = ?", (*fields.values(), session_id))

    def set_status(self, session_id: str, status: str, **fields) -> None:
        session = self.get(session_id)
        if not session or session["status"] in TERMINAL:
            return  # terminal states are final
        self.update(session_id, status=status, **fields)

    def due_to_start(self, lead: timedelta) -> list[dict]:
        return self._all("SELECT * FROM sessions WHERE status = 'scheduled' AND start_at <= ?", (iso(now() + lead),))

    def overdue(self) -> list[dict]:
        placeholders = ",".join("?" * (len(ACTIVE) + 1))
        return self._all(
            f"SELECT * FROM sessions WHERE status IN ({placeholders}) AND end_at <= ?",
            (*sorted(ACTIVE), "scheduled", iso(now())),
        )

    def overlapping(self, start: datetime, end: datetime) -> list[dict]:
        """Non-terminal sessions whose window overlaps [start, end): Cue hosts one demo at a time."""
        placeholders = ",".join("?" * len(TERMINAL))
        return self._all(
            f"SELECT * FROM sessions WHERE status NOT IN ({placeholders}) AND start_at < ? AND end_at > ?",
            (*sorted(TERMINAL), iso(end), iso(start)),
        )

    # -- rate limits ----------------------------------------------------------------------------

    def count_since(self, column: str, value: str, since: datetime) -> int:
        if column not in ("ip_hash", "email_hash"):
            raise ValueError(column)
        row = self._one(f"SELECT COUNT(*) AS n FROM sessions WHERE {column} = ? AND created_at >= ?", (digest(value, self.pepper), iso(since)))
        return row["n"] if row else 0

    def count_total_since(self, since: datetime) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM sessions WHERE created_at >= ?", (iso(since),))
        return row["n"] if row else 0

    def oldest_since(self, column: str, value: str, since: datetime) -> datetime | None:
        if column not in ("ip_hash", "email_hash"):
            raise ValueError(column)
        row = self._one(f"SELECT MIN(created_at) AS t FROM sessions WHERE {column} = ? AND created_at >= ?", (digest(value, self.pepper), iso(since)))
        return parse(row["t"]) if row and row["t"] else None

    # -- transcript and summary -----------------------------------------------------------------

    def add_turn(self, session_id: str, speaker: str, text: str) -> None:
        self._exec("INSERT INTO turns (session_id, at, speaker, text) VALUES (?,?,?,?)", (session_id, iso(now()), speaker, text[:2000]))

    def turns(self, session_id: str) -> list[dict]:
        return self._all("SELECT at, speaker, text FROM turns WHERE session_id = ? ORDER BY rowid", (session_id,))

    def set_summary(self, session_id: str, summary: dict) -> None:
        self.update(session_id, summary=json.dumps(summary))

    def summary(self, session_id: str) -> dict | None:
        session = self.get(session_id)
        return json.loads(session["summary"]) if session and session["summary"] else None

    # -- retention ------------------------------------------------------------------------------

    def purge(self, transcript_days: int, session_days: int) -> tuple[int, int]:
        turns = self._exec("DELETE FROM turns WHERE at < ?", (iso(now() - timedelta(days=transcript_days)),))
        sessions = self._exec("DELETE FROM sessions WHERE created_at < ?", (iso(now() - timedelta(days=session_days)),))
        return turns, sessions
