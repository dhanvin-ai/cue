"""Secret access for connector credentials.

Deployed refs are Secret Manager resource names. Local development may instead use
`file:NAME/versions/latest`, which reads `.secrets/NAME.json` (gitignored) with the same
access/add-version interface, so OAuth refreshes work without a GCP project.
"""

import os
from pathlib import Path
from types import SimpleNamespace

FILE_PREFIX = "file:"


def _directory() -> Path:
    return Path(os.getenv("CUE_SECRETS_DIR") or Path(__file__).resolve().parents[2] / ".secrets")


class FileSecretStore:
    def _path(self, name: str) -> Path:
        secret = name.removeprefix(FILE_PREFIX).split("/versions/", 1)[0]
        if not secret or "/" in secret or "\\" in secret or secret.startswith("."):
            raise ValueError("Invalid local secret name")
        # Names with an extension (github-app.pem) are used as-is; others are JSON grants.
        return _directory() / (secret if "." in secret else f"{secret}.json")

    def access_secret_version(self, name: str):
        return SimpleNamespace(payload=SimpleNamespace(data=self._path(name).read_bytes()))

    def add_secret_version(self, parent: str, payload: dict):
        path = self._path(parent)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload["data"])

    def write(self, name: str, data: bytes) -> str:
        self.add_secret_version(name, {"data": data})
        return f"{FILE_PREFIX}{name.removeprefix(FILE_PREFIX).split('/versions/', 1)[0]}/versions/latest"


def store_for(ref: str):
    if ref.startswith(FILE_PREFIX):
        return FileSecretStore()
    from google.cloud import secretmanager

    return secretmanager.SecretManagerServiceClient()


def read(ref: str) -> bytes:
    return store_for(ref).access_secret_version(name=ref).payload.data
