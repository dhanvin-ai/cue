"""Qwen3 embeddings and tenant-isolated Qdrant collections."""

import os
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5

import httpx

from cue.connectors.github import secret


def _auth(secret_env: str) -> dict[str, str]:
    ref = os.getenv(secret_env)
    return {"api-key": secret(ref).decode()} if ref else {}


class QwenEmbedder:
    model = "Qwen/Qwen3-Embedding-0.6B"
    dimensions = 1024

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=45)

    def embed(self, value: str, *, query: bool = False) -> list[float]:
        content = ("Instruct: Retrieve relevant team work and decisions\nQuery: " + value) if query else value
        headers = {}
        if ref := os.getenv("EMBEDDING_API_KEY_SECRET_VERSION"):
            headers["Authorization"] = "Bearer " + secret(ref).decode()
        response = self.client.post(
            os.environ["EMBEDDING_BASE_URL"].rstrip("/") + "/v1/embeddings",
            headers=headers, json={"model": self.model, "input": content},
        )
        response.raise_for_status()
        vector = response.json()["data"][0]["embedding"]
        if len(vector) != self.dimensions:
            raise ValueError("Qwen3 embedding dimension does not match the Qdrant collection")
        return vector


class QdrantIndex:
    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=30)
        self._ready: set[UUID] = set()

    @staticmethod
    def collection(tenant_id: UUID) -> str:
        return f"cue_{tenant_id.hex}"

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.request(
            method, os.environ["QDRANT_URL"].rstrip("/") + path,
            headers=_auth("QDRANT_API_KEY_SECRET_VERSION"), **kwargs,
        )

    def ensure_collection(self, tenant_id: UUID) -> None:
        if tenant_id in self._ready:
            return
        path = "/collections/" + self.collection(tenant_id)
        response = self._request("GET", path)
        if response.status_code == 404:
            created = self._request(
                "PUT", path, json={"vectors": {"size": QwenEmbedder.dimensions, "distance": "Cosine"}},
            )
            if created.status_code != 409:
                created.raise_for_status()
            for field in ("visibility", "principals"):
                indexed = self._request("PUT", path + "/index?wait=true",
                                        json={"field_name": field, "field_schema": "keyword"})
                indexed.raise_for_status()
        else:
            response.raise_for_status()
            size = response.json()["result"]["config"]["params"]["vectors"]["size"]
            if size != QwenEmbedder.dimensions:
                raise ValueError("Qdrant collection dimension does not match Qwen3")
        self._ready.add(tenant_id)

    def upsert(self, tenant_id: UUID, event: dict, vector: list[float]) -> None:
        self.ensure_collection(tenant_id)
        point_id = str(uuid5(NAMESPACE_URL, f"cue:{tenant_id}:{event['event_id']}"))
        response = self._request(
            "PUT", f"/collections/{self.collection(tenant_id)}/points?wait=true",
            json={"points": [{"id": point_id, "vector": vector, "payload": {
                "event_id": event["event_id"], "visibility": event["acl"]["visibility"],
                "principals": event["acl"]["principals"], "source": event["source"],
            }}]},
        )
        response.raise_for_status()

    def search(self, tenant_id: UUID, vector: list[float], principals: set[str], limit: int) -> list[str]:
        allowed = [{"key": "visibility", "match": {"value": "public"}}]
        if principals:
            allowed.append({"key": "principals", "match": {"any": sorted(principals)}})
        response = self._request(
            "POST", f"/collections/{self.collection(tenant_id)}/points/query",
            json={"query": vector, "filter": {"should": allowed},
                  "limit": limit, "with_payload": ["event_id"]},
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return [point["payload"]["event_id"] for point in response.json()["result"]["points"]]
