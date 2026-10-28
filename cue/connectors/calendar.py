from datetime import datetime
from typing import Any, Iterable, Mapping
from urllib.parse import quote, urlencode
from uuid import UUID, uuid4
import hashlib
import hmac
import os

import httpx

from cue.connectors.base import AccessControl, CanonicalEvent, Tool
from cue.connectors.credentials import Credential
from cue.connectors.github import secret
from cue.connectors.normalize_v1 import normalize


class CalendarConnector:
    provider = "calendar"
    API = "https://www.googleapis.com/calendar/v3"

    def __init__(self, credential: Credential, owner: str, client: httpx.Client | None = None):
        self.credential, self.owner = credential, owner
        self.client = client or httpx.Client(timeout=20)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.client.request(
            method, self.API + path,
            headers={"Authorization": f"Bearer {self.credential.token()}"}, **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def authorize(self, external_id: str) -> None:
        self._request("GET", f"/calendars/{quote(external_id, safe='')}")

    def backfill(self, external_id: str, since: datetime) -> Iterable[Mapping[str, Any]]:
        path = f"/calendars/{quote(external_id, safe='')}/events"
        page = None
        while True:
            params = {"updatedMin": since.isoformat(), "showDeleted": "true", "maxResults": 2500}
            if page:
                params["pageToken"] = page
            result = self._request("GET", path, params=params)
            for event in result.get("items", []):
                yield {"event": event, "calendar_id": external_id, "owner": self.owner}
            page = result.get("nextPageToken")
            if not page:
                break

    def subscribe(self) -> None:
        calendar_id = quote(self.owner, safe="")
        signature = hmac.new(secret(os.environ["CALENDAR_CHANNEL_SECRET_VERSION"]), self.owner.encode(), hashlib.sha256).hexdigest()
        self._request(
            "POST", f"/calendars/{calendar_id}/events/watch",
            json={"id": str(uuid4()), "type": "web_hook", "address": os.environ["CALENDAR_WEBHOOK_URL"],
                  "token": urlencode({"owner": self.owner, "signature": signature})},
        )

    def normalize(self, raw: Mapping[str, Any], tenant_id: UUID) -> CanonicalEvent:
        return normalize(self.provider, raw, tenant_id)

    def acl(self, raw: Mapping[str, Any]) -> AccessControl:
        return self.normalize(raw, UUID(int=0)).acl

    def tools(self) -> tuple[Tool, ...]:
        return (Tool("calendar.read_event", 0), Tool("calendar.create_event", 2))

    def create_event(self, calendar_id: str, summary: str, start: str, end: str, attendees: list[str]) -> Any:
        return self._request(
            "POST", f"/calendars/{quote(calendar_id, safe='')}/events",
            params={"sendUpdates": "all"},
            json={"summary": summary, "start": {"dateTime": start}, "end": {"dateTime": end},
                  "attendees": [{"email": address} for address in attendees]},
        )
