from datetime import datetime
from typing import Any, Iterable, Mapping
from uuid import UUID

import httpx

from cue.connectors.base import AccessControl, CanonicalEvent, Tool
from cue.connectors.credentials import Credential
from cue.connectors.normalize_v1 import normalize


class SlackConnector:
    provider = "slack"
    API = "https://slack.com/api"

    def __init__(self, credential: Credential, client: httpx.Client | None = None):
        self.credential = credential
        self.client = client or httpx.Client(timeout=20)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.client.request(
            method, self.API + path,
            headers={"Authorization": f"Bearer {self.credential.token()}"}, **kwargs,
        )
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(f"Slack API error: {result.get('error', 'unknown')}")
        return result

    def authorize(self, external_id: str) -> None:
        if self._request("POST", "/auth.test")["team_id"] != external_id:
            raise ValueError("Slack workspace does not match connection")

    def backfill(self, external_id: str, since: datetime) -> Iterable[Mapping[str, Any]]:
        cursor = None
        while True:
            params = {"types": "public_channel,private_channel,im,mpim", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            channels = self._request("GET", "/conversations.list", params=params)
            for channel in channels.get("channels", []):
                if channel.get("is_member") is False:
                    continue
                page = None
                while True:
                    history_params = {"channel": channel["id"], "oldest": str(since.timestamp()), "limit": 100}
                    if page:
                        history_params["cursor"] = page
                    history = self._request("GET", "/conversations.history", params=history_params)
                    for item in history.get("messages", []):
                        if item.get("type") == "message" and not item.get("subtype"):
                            yield {"event": {**item, "channel": channel["id"]}, "team_id": external_id}
                    page = history.get("response_metadata", {}).get("next_cursor")
                    if not page:
                        break
            cursor = channels.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

    def subscribe(self) -> None:
        self._request("POST", "/auth.test")  # Events API subscriptions are configured on the Slack app.

    def normalize(self, raw: Mapping[str, Any], tenant_id: UUID) -> CanonicalEvent:
        return normalize(self.provider, raw, tenant_id)

    def acl(self, raw: Mapping[str, Any]) -> AccessControl:
        return self.normalize(raw, UUID(int=0)).acl

    def tools(self) -> tuple[Tool, ...]:
        return (Tool("slack.read_channel", 0), Tool("slack.post_message", 1))

    def post_message(self, channel: str, text: str) -> Any:
        return self._request("POST", "/chat.postMessage", json={"channel": channel, "text": text})
