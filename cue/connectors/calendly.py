from datetime import datetime
from typing import Any, Iterable, Mapping
from uuid import UUID

import httpx

from cue.connectors.base import AccessControl, CanonicalEvent, Tool
from cue.connectors.credentials import Credential
from cue.connectors.normalize_v1 import normalize


class CalendlyConnector:
    """Calendly v2 with a personal access token; the external ID is the account email."""

    provider = "calendly"
    API = "https://api.calendly.com"

    def __init__(self, credential: Credential, client: httpx.Client | None = None):
        self.credential = credential
        self.client = client or httpx.Client(timeout=20)
        self._user: dict | None = None

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = path if path.startswith("https://") else self.API + path
        response = self.client.request(
            method, url, headers={"Authorization": f"Bearer {self.credential.token()}"}, **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def user(self) -> dict:
        if self._user is None:
            self._user = self._request("GET", "/users/me")["resource"]
        return self._user

    def _pages(self, path: str, params: dict) -> Iterable[dict]:
        url, query = path, dict(params)
        while url:
            result = self._request("GET", url, params=query)
            yield from result.get("collection", [])
            url, query = (result.get("pagination") or {}).get("next_page"), None

    def authorize(self, external_id: str) -> None:
        if self.user()["email"].casefold() != external_id.casefold():
            raise ValueError("Calendly account does not match connection")

    def backfill(self, external_id: str, since: datetime) -> Iterable[Mapping[str, Any]]:
        owner = self.user()
        # Calendly filters by start time, not update time, so reruns re-read upcoming events;
        # event IDs carry updated_at, so unchanged events deduplicate downstream.
        for event in self._pages("/scheduled_events", {
                "user": owner["uri"], "min_start_time": since.isoformat(), "count": 100,
                "sort": "start_time:asc"}):
            invitees = list(self._pages(f"{event['uri']}/invitees", {"count": 100}))
            yield {"event": event, "invitees": invitees, "owner": external_id.casefold()}

    def subscribe(self) -> None:
        # Webhook subscriptions need a paid Calendly plan; polling covers the free tier.
        return None

    def normalize(self, raw: Mapping[str, Any], tenant_id: UUID) -> CanonicalEvent:
        return normalize(self.provider, raw, tenant_id)

    def acl(self, raw: Mapping[str, Any]) -> AccessControl:
        return self.normalize(raw, UUID(int=0)).acl

    def tools(self) -> tuple[Tool, ...]:
        return (Tool("calendly.list_event_types", 0), Tool("calendly.create_booking_link", 1))

    def list_event_types(self) -> list[dict]:
        return [{"name": item["name"], "duration": item.get("duration"),
                 "scheduling_url": item["scheduling_url"], "uri": item["uri"]}
                for item in self._pages("/event_types", {"user": self.user()["uri"],
                                                         "active": "true", "count": 100})]

    def create_booking_link(self, event_type_uri: str) -> str:
        """Single-use link; sending it to someone outside the team is a separate tier 3 action."""
        result = self._request("POST", "/scheduling_links", json={
            "max_event_count": 1, "owner": event_type_uri, "owner_type": "EventType"})
        return result["resource"]["booking_url"]
