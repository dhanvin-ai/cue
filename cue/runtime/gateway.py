"""Model gateway with a primary frontier provider and a fallback.

The planner and the responder use this interface. Calls go through LiteLLM (or
any OpenAI-compatible gateway); the gateway handles provider credentials and
per-tenant cost. The agent never talks to a model vendor directly.
"""

import json
import os
from dataclasses import dataclass
from typing import Protocol

import httpx

from cue.connectors.github import secret


class ModelUnavailable(RuntimeError):
    """Every configured provider failed."""


@dataclass(frozen=True)
class Completion:
    text: str
    provider: str


class Gateway(Protocol):
    def complete(self, messages: list[dict], *, model_class: str = "planner") -> Completion: ...


class LiteLLMGateway:
    """OpenAI-compatible gateway call with ordered provider fallback."""

    def __init__(self, models: list[str] | None = None, client: httpx.Client | None = None):
        self.models = models or [
            os.getenv("AGENT_PRIMARY_MODEL", "gemini-2.5-pro"),
            os.getenv("AGENT_FALLBACK_MODEL", "claude-sonnet-4-5"),
        ]
        if len(self.models) < 2:
            raise ValueError("At least a primary and a fallback model are required")
        self.client = client or httpx.Client(timeout=90)

    def _headers(self) -> dict[str, str]:
        if ref := os.getenv("MODEL_GATEWAY_API_KEY_SECRET_VERSION"):
            return {"Authorization": "Bearer " + secret(ref).decode()}
        return {}

    def complete(self, messages: list[dict], *, model_class: str = "planner") -> Completion:
        url = os.environ["MODEL_GATEWAY_BASE_URL"].rstrip("/") + "/v1/chat/completions"
        failures = []
        for model in self.models:
            body = {"model": model, "temperature": 0, "messages": messages}
            if model_class == "planner":
                body["response_format"] = {"type": "json_object"}
            try:
                response = self.client.post(url, headers=self._headers(), json=body)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                if not content or not content.strip():
                    raise ValueError("Empty completion")
                return Completion(text=content, provider=model)
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                failures.append(f"{model}: {type(exc).__name__}")
        raise ModelUnavailable("All model providers failed: " + ", ".join(failures))


def json_reply(completion: Completion) -> dict:
    try:
        value = json.loads(completion.text)
    except json.JSONDecodeError as exc:
        raise ValueError("Model did not return JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Model did not return a JSON object")
    return value
