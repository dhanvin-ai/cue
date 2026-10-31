"""Google Calendar + Meet for the demo, as Cue's own Google account.

The OAuth refresh token lives in a server-side file written by scripts/demo_google_auth.py
(mode 0600, outside the repo). Access tokens are refreshed here and never leave the server.
Scope: calendar.events only, so the demo can create and cancel its own events and nothing else.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

API = "https://www.googleapis.com/calendar/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/calendar.events"


class GoogleError(RuntimeError):
    pass


@dataclass(frozen=True)
class Meeting:
    event_id: str
    meet_url: str
    html_link: str | None


class Calendar(Protocol):
    async def create_meeting(self, *, summary: str, description: str, start: str, end: str,
                             attendee: str, request_id: str) -> Meeting: ...

    async def cancel(self, event_id: str) -> None: ...


class TokenFile:
    """Refresh-token credential stored in a local JSON file."""

    def __init__(self, path: Path, client: httpx.AsyncClient):
        self.path = path
        self.client = client
        self._lock = asyncio.Lock()

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError) as error:
            raise GoogleError(f"Google token file unreadable: {self.path}") from error

    async def token(self) -> str:
        async with self._lock:
            data = self._read()
            if data.get("access_token") and data.get("expires_at", 0) > time.time() + 60:
                return data["access_token"]
            response = await self.client.post(TOKEN_URL, data={
                "grant_type": "refresh_token", "refresh_token": data["refresh_token"],
                "client_id": data["client_id"], "client_secret": data["client_secret"],
            })
            if response.status_code != 200:
                raise GoogleError(f"Google token refresh failed ({response.status_code}); re-run scripts/demo_google_auth.py")
            fresh = response.json()
            data["access_token"] = fresh["access_token"]
            data["expires_at"] = time.time() + int(fresh.get("expires_in", 3600))
            write_private(self.path, data)
            return data["access_token"]


def write_private(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(data, out)
    os.replace(tmp, path)


class GoogleCalendar:
    def __init__(self, token_file: Path, calendar_id: str = "primary", client: httpx.AsyncClient | None = None):
        self.client = client or httpx.AsyncClient(timeout=20)
        self.credential = TokenFile(token_file, self.client)
        self.calendar = quote(calendar_id, safe="")

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        token = await self.credential.token()
        response = await self.client.request(method, API + path, headers={"Authorization": f"Bearer {token}"}, **kwargs)
        if response.status_code >= 400:
            try:
                message = response.json().get("error", {}).get("message", "")
            except ValueError:
                message = ""
            raise GoogleError(f"Google Calendar {response.status_code}: {message or response.reason_phrase}")
        return response.json() if response.content else {}

    async def create_meeting(self, *, summary: str, description: str, start: str, end: str,
                             attendee: str, request_id: str) -> Meeting:
        event = await self._request(
            "POST", f"/calendars/{self.calendar}/events",
            params={"conferenceDataVersion": 1, "sendUpdates": "all"},
            json={
                "summary": summary,
                "description": description,
                "start": {"dateTime": start},
                "end": {"dateTime": end},
                "attendees": [{"email": attendee}],
                "guestsCanInviteOthers": False,
                "guestsCanSeeOtherGuests": False,
                "visibility": "private",
                "reminders": {"useDefault": False, "overrides": [{"method": "email", "minutes": 10}]},
                "conferenceData": {"createRequest": {"requestId": request_id, "conferenceSolutionKey": {"type": "hangoutsMeet"}}},
            },
        )
        # Meet links are usually ready immediately; poll briefly when the request is still pending.
        for _ in range(10):
            meet = event.get("hangoutLink") or next(
                (p.get("uri") for p in event.get("conferenceData", {}).get("entryPoints", []) if p.get("entryPointType") == "video"), None)
            if meet:
                return Meeting(event["id"], meet, event.get("htmlLink"))
            await asyncio.sleep(0.5)
            event = await self._request("GET", f"/calendars/{self.calendar}/events/{quote(event['id'], safe='')}")
        raise GoogleError("Google created the event but no Meet link; is Google Meet enabled for Cue's account?")

    async def cancel(self, event_id: str) -> None:
        await self._request("DELETE", f"/calendars/{self.calendar}/events/{quote(event_id, safe='')}", params={"sendUpdates": "all"})
