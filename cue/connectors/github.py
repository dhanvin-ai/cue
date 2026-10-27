import hashlib
import hmac
import os
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import quote
from uuid import UUID

import httpx
import jwt
from google.cloud import secretmanager

from cue.connectors.base import AccessControl, CanonicalEvent, Tool

API = "https://api.github.com"
REQUIRED_EVENTS = {"installation", "issues", "pull_request"}


def secret(ref: str) -> bytes:
    return secretmanager.SecretManagerServiceClient().access_secret_version(name=ref).payload.data


def verify_webhook(body: bytes, signature: str | None, key: bytes) -> bool:
    expected = "sha256=" + hmac.new(key, body, hashlib.sha256).hexdigest()
    return bool(signature) and hmac.compare_digest(expected, signature)


class GitHubConnector:
    provider = "github"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=15)
        self._cached_token: tuple[str, str, float] | None = None

    def _app_jwt(self) -> str:
        now = int(time.time())
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": os.environ["GITHUB_APP_ID"]},
            secret(os.environ["GITHUB_PRIVATE_KEY_SECRET_VERSION"]),
            algorithm="RS256",
        )

    def _request(self, method: str, path: str, token: str, **kwargs: Any) -> Any:
        response = self.client.request(
            method,
            API + path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2026-03-10",
            },
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def authorize(self, external_id: str) -> None:
        self._request("GET", f"/app/installations/{int(external_id)}", self._app_jwt())

    def subscribe(self) -> None:
        app = self._request("GET", "/app", self._app_jwt())
        missing = REQUIRED_EVENTS - set(app.get("events", []))
        if missing:
            raise RuntimeError(f"GitHub App webhook events missing: {', '.join(sorted(missing))}")

    def _installation_token(self, external_id: str) -> str:
        if self._cached_token and self._cached_token[0] == external_id:
            _, token, expires_at = self._cached_token
            if expires_at > datetime.now(timezone.utc).timestamp() + 60:
                return token
        result = self._request(
            "POST", f"/app/installations/{int(external_id)}/access_tokens", self._app_jwt()
        )
        expires_at = datetime.fromisoformat(result["expires_at"].replace("Z", "+00:00"))
        self._cached_token = (external_id, result["token"], expires_at.timestamp())
        return result["token"]

    def _pages(self, path: str, external_id: str, params: dict[str, Any] | None = None) -> Iterable[Any]:
        page = 1
        while True:
            result = self._request(
                "GET", path, self._installation_token(external_id),
                params={**(params or {}), "per_page": 100, "page": page},
            )
            items = result["repositories"] if path == "/installation/repositories" else result
            yield from items
            if len(items) < 100:
                return
            page += 1

    def backfill(self, external_id: str, since: datetime) -> Iterable[Mapping[str, Any]]:
        since_utc = since.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        for repo in self._pages("/installation/repositories", external_id):
            owner = quote(repo["owner"]["login"], safe="")
            name = quote(repo["name"], safe="")
            for issue in self._pages(
                f"/repos/{owner}/{name}/issues", external_id, {"state": "all", "since": since_utc}
            ):
                yield {"event": "snapshot", "issue": issue, "repository": repo}

    def acl(self, raw: Mapping[str, Any]) -> AccessControl:
        repo = raw["repository"]
        if repo["private"]:
            return AccessControl("restricted", (f"github:repo:{repo['id']}",))
        return AccessControl("public", ())

    def normalize(self, raw: Mapping[str, Any], tenant_id: UUID) -> CanonicalEvent:
        item = raw.get("issue") or raw.get("pull_request")
        if item is None:
            raise ValueError("Expected a GitHub issue or pull request")
        kind = "pr" if "pull_request" in raw or "pull_request" in item else "issue"
        updated = datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00"))
        repository = raw["repository"]
        action = raw.get("action", "snapshot")
        if kind == "pr" and action == "closed" and item.get("merged"):
            action = "merged"
            if item.get("merged_at"):
                updated = datetime.fromisoformat(item["merged_at"].replace("Z", "+00:00"))
        return CanonicalEvent(
            tenant_id=tenant_id,
            event_id=f"gh:{kind}:{item['id']}:{item['updated_at']}:{raw.get('action', 'snapshot')}",
            source="github",
            type=f"{kind}.{action}",
            occurred_at=updated,
            actors=(f"github:user:{(raw.get('sender') or item['user'])['id']}",),
            objects=(f"github:{kind}:{item['id']}", f"github:repo:{repository['id']}"),
            text=f"{item['title']}\n{item.get('body') or ''}",
            acl=self.acl(raw),
        )

    def tools(self) -> tuple[Tool, ...]:
        return (Tool("github.read_issue", 0),)
