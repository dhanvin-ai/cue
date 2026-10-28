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
GRAPHQL = """
query CueBackfill($owner: String!, $name: String!, $since: DateTime!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(first: 100, after: $cursor, states: [OPEN, CLOSED],
           filterBy: {since: $since}, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { databaseId number title body state updatedAt
              author { ... on User { databaseId } }
              assignees(first: 1) { nodes { databaseId login } } }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""
PULLS_GRAPHQL = """
query CuePullBackfill($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: 100, after: $cursor, states: [OPEN, CLOSED, MERGED],
                 orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { databaseId number title body state updatedAt mergedAt
              author { ... on User { databaseId } }
              assignees(first: 1) { nodes { databaseId login } } }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""
REQUIRED_EVENTS = {
    "installation", "issues", "pull_request", "push", "issue_comment",
    "pull_request_review", "pull_request_review_comment",
}


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

    def _graphql_pages(self, external_id: str, repo: Mapping[str, Any], since: str,
                       kind: str) -> Iterable[Mapping[str, Any]]:
        cursor = None
        while True:
            variables = {"owner": repo["owner"]["login"], "name": repo["name"], "cursor": cursor}
            if kind == "issues":
                variables["since"] = since
            result = self._request(
                "POST", "/graphql", self._installation_token(external_id),
                json={"query": GRAPHQL if kind == "issues" else PULLS_GRAPHQL, "variables": variables},
            )
            if result.get("errors"):
                raise RuntimeError(f"GitHub GraphQL backfill failed: {result['errors']}")
            connection = result["data"]["repository"][kind]
            for node in connection["nodes"]:
                if node.get("databaseId"):
                    yield node
            info = connection["pageInfo"]
            if not info["hasNextPage"]:
                return
            cursor = info["endCursor"]

    def backfill(self, external_id: str, since: datetime) -> Iterable[Mapping[str, Any]]:
        since_utc = since.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        for repo in self._pages("/installation/repositories", external_id):
            owner = quote(repo["owner"]["login"], safe="")
            name = quote(repo["name"], safe="")
            for node in self._graphql_pages(external_id, repo, since_utc, "issues"):
                assignees = (node.get("assignees") or {}).get("nodes") or []
                issue = {"id": node["databaseId"], "number": node.get("number"),
                         "state": (node.get("state") or "").lower(), "assignee": (
                             {"id": assignees[0]["databaseId"], "login": assignees[0]["login"]}
                             if assignees else None), "title": node["title"],
                         "body": node.get("body"), "updated_at": node["updatedAt"],
                         "user": {"id": (node.get("author") or {}).get("databaseId")}}
                yield {"event": "snapshot", "issue": issue, "repository": repo}
            for commit in self._pages(
                f"/repos/{owner}/{name}/commits", external_id, {"since": since_utc}
            ):
                yield {"event": "snapshot", "commit": commit, "repository": repo}
            for comment in self._pages(
                f"/repos/{owner}/{name}/issues/comments", external_id, {"since": since_utc}
            ):
                yield {"event": "snapshot", "comment": comment, "repository": repo}
            for node in self._graphql_pages(external_id, repo, since_utc, "pullRequests"):
                if node["updatedAt"] < since_utc:
                    break
                assignees = (node.get("assignees") or {}).get("nodes") or []
                pull = {"id": node["databaseId"], "number": node["number"],
                        "state": (node.get("state") or "").lower(), "assignee": (
                            {"id": assignees[0]["databaseId"], "login": assignees[0]["login"]}
                            if assignees else None),
                        "title": node["title"], "body": node.get("body"),
                        "updated_at": node["updatedAt"], "merged_at": node.get("mergedAt"),
                        "user": {"id": (node.get("author") or {}).get("databaseId")}}
                yield {"event": "snapshot", "pull_request": pull, "repository": repo}
                for review in self._pages(
                    f"/repos/{owner}/{name}/pulls/{pull['number']}/reviews", external_id
                ):
                    if review.get("submitted_at") and review["submitted_at"] >= since_utc:
                        yield {
                            "event": "snapshot", "review": review,
                            "pull_request": pull, "repository": repo,
                        }

    def acl(self, raw: Mapping[str, Any]) -> AccessControl:
        repo = raw["repository"]
        if repo["private"]:
            return AccessControl("restricted", (f"github:repo:{repo['id']}",))
        return AccessControl("public", ())

    def normalize(self, raw: Mapping[str, Any], tenant_id: UUID) -> CanonicalEvent:
        repo = raw["repository"]
        actor = raw.get("sender")
        if "commits" in raw:
            commits = raw["commits"]
            head = raw.get("head_commit") or (commits[-1] if commits else {})
            timestamp = head.get("timestamp") or datetime.now(timezone.utc).isoformat()
            return CanonicalEvent(
                tenant_id, f"gh:push:{repo['id']}:{raw['after']}", "github", "push",
                datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
                (f"github:user:{actor['id']}",) if actor and actor.get("id") else (),
                tuple(f"github:commit:{item['id']}" for item in commits) + (f"github:repo:{repo['id']}",),
                "\n".join(item.get("message", "") for item in commits), self.acl(raw),
            )
        if "commit" in raw:
            item = raw["commit"]
            author = item.get("author") or actor or {}
            timestamp = item.get("commit", {}).get("author", {}).get("date") or item.get("timestamp")
            return CanonicalEvent(
                tenant_id, f"gh:commit:{item['sha']}", "github", "commit.pushed",
                datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
                (f"github:user:{author['id']}",) if author.get("id") else (),
                (f"github:commit:{item['sha']}", f"github:repo:{repo['id']}"),
                item.get("commit", {}).get("message") or item.get("message", ""), self.acl(raw),
            )
        if "review" in raw:
            item = raw["review"]
            author = actor or item.get("user") or {}
            pull = raw.get("pull_request") or {}
            return CanonicalEvent(
                tenant_id, f"gh:review:{item['id']}:{item.get('submitted_at') or item.get('updated_at')}",
                "github", f"review.{raw.get('action', 'snapshot')}",
                datetime.fromisoformat((item.get("submitted_at") or item["updated_at"]).replace("Z", "+00:00")),
                (f"github:user:{author['id']}",) if author.get("id") else (),
                (f"github:review:{item['id']}", f"github:repo:{repo['id']}") +
                ((f"github:pr:{pull['id']}",) if pull.get("id") else ()),
                item.get("body") or "", self.acl(raw),
            )
        if "comment" in raw:
            item = raw["comment"]
            author = actor or item.get("user") or {}
            target = raw.get("issue") or raw.get("pull_request") or {}
            return CanonicalEvent(
                tenant_id, f"gh:comment:{item['id']}:{item['updated_at']}", "github",
                f"comment.{raw.get('action', 'snapshot')}",
                datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00")),
                (f"github:user:{author['id']}",) if author.get("id") else (),
                (f"github:comment:{item['id']}", f"github:repo:{repo['id']}") +
                ((f"github:{'pr' if 'pull_request' in target else 'issue'}:{target['id']}",)
                 if target.get("id") else ()),
                item.get("body") or "", self.acl(raw),
            )
        item = raw.get("issue") or raw.get("pull_request")
        if item is None:
            raise ValueError("Expected a GitHub issue or pull request")
        kind = "pr" if "pull_request" in raw or "pull_request" in item else "issue"
        updated = datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00"))
        repository = repo
        action = raw.get("action", "snapshot")
        if kind == "pr" and action in {"closed", "snapshot"} and (item.get("merged") or item.get("merged_at")):
            action = "merged"
            if item.get("merged_at"):
                updated = datetime.fromisoformat(item["merged_at"].replace("Z", "+00:00"))
        assignee = item.get("assignee") or {}
        facts = {"state": item.get("state")}
        if "assignee" in item:
            facts["owner_alias"] = f"github:user:{assignee['id']}" if assignee.get("id") else None
            facts["owner_label"] = assignee.get("login")
        return CanonicalEvent(
            tenant_id=tenant_id,
            event_id=f"gh:{kind}:{item['id']}:{item['updated_at']}:{raw.get('action', 'snapshot')}",
            source="github",
            type=f"{kind}.{action}",
            occurred_at=updated,
            actors=((f"github:user:{(raw.get('sender') or item.get('user') or {}).get('id')}",)
                    if (raw.get('sender') or item.get('user') or {}).get('id') else ()),
            objects=(f"github:{kind}:{item['id']}", f"github:repo:{repository['id']}"),
            text=f"{item['title']}\n{item.get('body') or ''}\n{assignee.get('login') or ''}",
            acl=self.acl(raw),
            facts=facts,
        )

    def tools(self) -> tuple[Tool, ...]:
        return (
            Tool("github.read_issue", 0), Tool("github.create_issue", 2),
            Tool("github.comment_issue", 2), Tool("github.request_review", 2),
        )

    def read_issue(self, installation_id: str, owner: str, repo: str, number: int) -> tuple[dict, dict]:
        path = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
        token = self._installation_token(installation_id)
        repository = self._request("GET", path, token)
        issue = self._request("GET", f"{path}/issues/{int(number)}", token)
        return repository, issue

    def create_issue(self, installation_id: str, owner: str, repo: str, title: str, body: str) -> Any:
        path = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/issues"
        return self._request("POST", path, self._installation_token(installation_id), json={"title": title, "body": body})

    def comment_issue(self, installation_id: str, owner: str, repo: str, number: int, body: str) -> Any:
        path = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/issues/{int(number)}/comments"
        return self._request("POST", path, self._installation_token(installation_id), json={"body": body})

    def request_review(self, installation_id: str, owner: str, repo: str, number: int, reviewers: list[str]) -> Any:
        path = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/pulls/{int(number)}/requested_reviewers"
        return self._request("POST", path, self._installation_token(installation_id), json={"reviewers": reviewers})
