from datetime import datetime
from typing import Any, Iterable, Mapping
from uuid import UUID

import httpx

from cue.connectors.base import AccessControl, CanonicalEvent, Tool
from cue.connectors.credentials import Credential
from cue.connectors.normalize_v1 import normalize


class LinearConnector:
    provider = "linear"
    API = "https://api.linear.app/graphql"

    def __init__(self, credential: Credential, client: httpx.Client | None = None):
        self.credential = credential
        self.client = client or httpx.Client(timeout=20)

    def _query(self, query: str, variables: dict | None = None) -> dict:
        response = self.client.post(
            self.API, headers={"Authorization": f"Bearer {self.credential.token()}"},
            json={"query": query, "variables": variables or {}},
        )
        response.raise_for_status()
        result = response.json()
        if result.get("errors"):
            raise RuntimeError(f"Linear GraphQL error: {result['errors'][0].get('message', 'unknown')}")
        return result["data"]

    def authorize(self, external_id: str) -> None:
        if self._query("{ organization { id } }")["organization"]["id"] != external_id:
            raise ValueError("Linear organization does not match connection")

    def backfill(self, external_id: str, since: datetime) -> Iterable[Mapping[str, Any]]:
        query = """query($after: String) {
          issues(first: 100, after: $after, orderBy: updatedAt) {
            nodes { id identifier title description updatedAt team { id } assignee { id name }
                    state { id name } cycle { id name } project { id name } }
            pageInfo { hasNextPage endCursor }
          }
        }"""
        cursor = None
        while True:
            result = self._query(query, {"after": cursor})["issues"]
            for item in result["nodes"]:
                if datetime.fromisoformat(item["updatedAt"].replace("Z", "+00:00")) >= since:
                    yield {"type": "Issue", "action": "snapshot", "data": item,
                           "organizationId": external_id}
            if not result["pageInfo"]["hasNextPage"]:
                break
            cursor = result["pageInfo"]["endCursor"]

    def subscribe(self) -> None:
        self._query("{ organization { id } }")  # Webhook is configured on the Linear OAuth application.

    def normalize(self, raw: Mapping[str, Any], tenant_id: UUID) -> CanonicalEvent:
        return normalize(self.provider, raw, tenant_id)

    def acl(self, raw: Mapping[str, Any]) -> AccessControl:
        return self.normalize(raw, UUID(int=0)).acl

    def tools(self) -> tuple[Tool, ...]:
        return (Tool("linear.read_issue", 0), Tool("linear.create_issue", 2))

    def read_issue(self, issue_id: str) -> dict:
        return self._query(
            "query($id: String!) { issue(id: $id) { id title url team { id } state { name } } }",
            {"id": issue_id},
        )["issue"]

    def create_issue(self, team_id: str, title: str, description: str) -> Any:
        data = self._query(
            "mutation($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { id identifier } } }",
            {"input": {"teamId": team_id, "title": title, "description": description}},
        )["issueCreate"]
        if not data["success"]:
            raise RuntimeError("Linear issue creation failed")
        return data["issue"]
