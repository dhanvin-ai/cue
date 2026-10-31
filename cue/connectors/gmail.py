from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Iterable, Mapping
from uuid import UUID
import base64
import os

import httpx

from cue.http import tls_context
from cue.connectors.base import AccessControl, CanonicalEvent, Tool
from cue.connectors.credentials import Credential
from cue.connectors.normalize_v1 import normalize


class GmailConnector:
    provider = "gmail"
    API = "https://gmail.googleapis.com/gmail/v1/users/me"

    def __init__(self, credential: Credential, client: httpx.Client | None = None):
        self.credential = credential
        self.client = client or httpx.Client(verify=tls_context(), timeout=20)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.client.request(
            method, self.API + path,
            headers={"Authorization": f"Bearer {self.credential.token()}"}, **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def authorize(self, external_id: str) -> None:
        profile = self._request("GET", "/profile")
        if profile["emailAddress"].casefold() != external_id.casefold():
            raise ValueError("Gmail account does not match connection")

    def backfill(self, external_id: str, since: datetime) -> Iterable[Mapping[str, Any]]:
        page = None
        after = int(since.astimezone(timezone.utc).timestamp())
        while True:
            params = {"q": f"after:{after}", "maxResults": 100}
            if page:
                params["pageToken"] = page
            result = self._request("GET", "/messages", params=params)
            for message in result.get("messages", []):
                full = self._request("GET", f"/messages/{message['id']}", params={"format": "full"})
                yield {"message": full, "mailbox": external_id}
            page = result.get("nextPageToken")
            if not page:
                break

    def subscribe(self) -> None:
        self._request("POST", "/watch", json={"topicName": os.environ["GMAIL_PUSH_TOPIC"]})

    def normalize(self, raw: Mapping[str, Any], tenant_id: UUID) -> CanonicalEvent:
        return normalize(self.provider, raw, tenant_id)

    def acl(self, raw: Mapping[str, Any]) -> AccessControl:
        return self.normalize(raw, UUID(int=0)).acl

    def tools(self) -> tuple[Tool, ...]:
        return (Tool("gmail.read_message", 0), Tool("gmail.create_draft", 1), Tool("gmail.send", 3))

    def create_draft(self, recipient: str, subject: str, body: str) -> Any:
        message = EmailMessage()
        message["To"], message["Subject"] = recipient, subject
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return self._request("POST", "/drafts", json={"message": {"raw": raw}})

    def send(self, recipient: str, subject: str, body: str) -> Any:
        message = EmailMessage()
        message["To"], message["Subject"] = recipient, subject
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return self._request("POST", "/messages/send", json={"raw": raw})
