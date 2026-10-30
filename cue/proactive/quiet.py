"""Per-tenant and per-person quiet hours with IANA time zones."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg


@dataclass(frozen=True)
class QuietWindow:
    timezone: str
    start: time
    end: time

    def zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown time zone {self.timezone!r}") from exc

    def contains(self, moment: datetime) -> bool:
        local = moment.astimezone(self.zone()).time()
        if self.start == self.end:
            return True
        if self.start < self.end:
            return self.start <= local < self.end
        return local >= self.start or local < self.end

    def release_at(self, moment: datetime) -> datetime:
        """Return the first moment outside the window, in UTC."""
        if not self.contains(moment):
            return moment.astimezone(timezone.utc)
        local = moment.astimezone(self.zone())
        end = datetime.combine(local.date(), self.end, tzinfo=local.tzinfo)
        if end <= local:
            end += timedelta(days=1)
        return end.astimezone(timezone.utc)


def window_for(database: psycopg.Connection, tenant_id, uid: str | None) -> QuietWindow | None:
    """A user row wins over the tenant row; no row means no quiet hours."""
    row = None
    if uid:
        row = database.execute(
            "SELECT timezone, start_time, end_time FROM quiet_hours "
            "WHERE tenant_id = %s AND scope = 'user' AND subject = %s",
            (tenant_id, uid),
        ).fetchone()
    if row is None:
        row = database.execute(
            "SELECT timezone, start_time, end_time FROM quiet_hours "
            "WHERE tenant_id = %s AND scope = 'tenant' AND subject = '*'",
            (tenant_id,),
        ).fetchone()
    return QuietWindow(*row) if row else None


def set_window(database: psycopg.Connection, tenant_id, *, scope: str, subject: str,
               timezone_name: str, start: time, end: time) -> QuietWindow:
    if scope not in {"tenant", "user"}:
        raise ValueError("Quiet hours scope must be tenant or user")
    window = QuietWindow(timezone_name, start, end)
    window.zone()  # validate before writing
    if scope == "tenant":
        subject = "*"
    database.execute(
        "INSERT INTO quiet_hours (tenant_id, scope, subject, timezone, start_time, end_time) "
        "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (tenant_id, scope, subject) DO UPDATE SET "
        "timezone = EXCLUDED.timezone, start_time = EXCLUDED.start_time, "
        "end_time = EXCLUDED.end_time",
        (tenant_id, scope, subject, timezone_name, start, end),
    )
    return window


def list_windows(database: psycopg.Connection, tenant_id) -> list[dict]:
    rows = database.execute(
        "SELECT scope, subject, timezone, start_time, end_time FROM quiet_hours "
        "WHERE tenant_id = %s ORDER BY scope, subject", (tenant_id,),
    ).fetchall()
    keys = ("scope", "subject", "timezone", "start_time", "end_time")
    return [dict(zip(keys, row)) for row in rows]


def deferral(database: psycopg.Connection, tenant_id, uid: str | None,
             moment: datetime) -> datetime | None:
    """Return the release time when proactive delivery must be deferred."""
    window = window_for(database, tenant_id, uid)
    if window is None or not window.contains(moment):
        return None
    return window.release_at(moment)
