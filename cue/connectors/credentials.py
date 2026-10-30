"""OAuth credentials live in Secret Manager (or a local file store); refreshes replace `latest`."""

import json
import time

import httpx
from cue.connectors import secret_store


class Credential:
    def __init__(self, ref: str, provider: str, client: httpx.Client | None = None, store=None):
        if not ref.endswith("/versions/latest"):
            raise ValueError("Connector secret_ref must point to /versions/latest")
        self.ref = ref
        self.provider = provider
        self.client = client or httpx.Client(timeout=15)
        self.store = store or secret_store.store_for(ref)

    def token(self) -> str:
        data = json.loads(self.store.access_secret_version(name=self.ref).payload.data)
        if data.get("expires_at", float("inf")) > time.time() + 60:
            return data["access_token"]
        if self.provider not in {"gmail", "calendar", "linear"} or not data.get("refresh_token"):
            raise ValueError("Connector authorization has expired")
        endpoint = (
            "https://oauth2.googleapis.com/token" if self.provider in {"gmail", "calendar"}
            else "https://api.linear.app/oauth/token"
        )
        response = self.client.post(endpoint, data={
            "grant_type": "refresh_token", "refresh_token": data["refresh_token"],
            "client_id": data["client_id"], "client_secret": data["client_secret"],
        })
        response.raise_for_status()
        refreshed = response.json()
        data.update(refreshed)
        data["expires_at"] = time.time() + int(refreshed["expires_in"])
        self.store.add_secret_version(
            parent=self.ref.split("/versions/", 1)[0],
            payload={"data": json.dumps(data).encode()},
        )
        return data["access_token"]
