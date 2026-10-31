from datetime import datetime
from typing import Any, Iterable, Mapping
from uuid import UUID

import httpx

from cue.http import tls_context
from cue.connectors.base import AccessControl, CanonicalEvent, Tool
from cue.connectors.normalize_v1 import normalize


class RecallConnector:
    provider = "recall"

    def __init__(self, api_key: str, region: str, client: httpx.Client | None = None):
        if region not in {"us-east-1", "us-west-2", "eu-central-1", "ap-northeast-1"}:
            raise ValueError("Unsupported Recall region")
        self.api_key = api_key
        self.API = f"https://{region}.recall.ai/api/v1"
        self.client = client or httpx.Client(verify=tls_context(), timeout=20)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.client.request(
            method, self.API + path,
            headers={"Authorization": f"Token {self.api_key}"}, **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def authorize(self, external_id: str) -> None:
        self._request("GET", f"/bot/{UUID(external_id)}/")

    def backfill(self, external_id: str, since: datetime) -> Iterable[Mapping[str, Any]]:
        bot = self._request("GET", f"/bot/{UUID(external_id)}/")
        yield {"event": "bot.snapshot", "data": {"bot": bot, "data": {"updated_at": bot.get("updated_at")}}}
        for recording in bot.get("recordings", []):
            url = recording.get("media_shortcuts", {}).get("transcript", {}).get("data", {}).get("download_url")
            if not url:
                continue
            response = self.client.get(url)
            response.raise_for_status()
            for index, segment in enumerate(response.json()):
                words = segment.get("words") or []
                timestamp = words[0].get("start_timestamp", {}).get("absolute") if words else None
                participant = segment.get("participant") or {}
                yield {"event": "transcript.segment", "data": {
                    "bot": bot,
                    "transcript": {
                        "segment_index": f"{recording['id']}:{index}",
                        "speaker_id": participant.get("id"),
                        "words": words,
                        "occurred_at": timestamp,
                    },
                }}

    def subscribe(self) -> None:
        pass  # Workspace webhook and real-time endpoint are configured in the Recall dashboard.

    def normalize(self, raw: Mapping[str, Any], tenant_id: UUID) -> CanonicalEvent:
        return normalize(self.provider, raw, tenant_id)

    def acl(self, raw: Mapping[str, Any]) -> AccessControl:
        return self.normalize(raw, UUID(int=0)).acl

    def tools(self) -> tuple[Tool, ...]:
        return (Tool("recall.read_bot", 0), Tool("recall.create_bot", 2))

    def create_bot(self, meeting_url: str, attendees: list[str], join_at: str | None = None) -> Any:
        if not meeting_url.startswith(("https://meet.google.com/", "https://zoom.us/", "https://us02web.zoom.us/")):
            raise ValueError("Only Google Meet and Zoom meeting URLs are supported")
        body = {
            "meeting_url": meeting_url,
            "bot_name": "Cue (AI teammate)",
            "metadata": {"attendees": attendees},
            "recording_config": {"transcript": {"provider": {"recallai_streaming": {"mode": "prioritize_low_latency", "language_code": "en"}}}},
        }
        if join_at:
            body["join_at"] = join_at
        return self._request("POST", "/bot/", json=body)
