"""Model gateway with a primary frontier provider and a fallback.

The planner and the responder use this interface. Calls go through LiteLLM (or
any OpenAI-compatible gateway); the gateway handles provider credentials and
per-tenant cost. The agent never talks to a model vendor directly.
"""

import json
import os
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from cue.http import tls_context
from cue.connectors.github import secret


def _completions_url(base: str) -> str:
    """Gemini's OpenAI-compatible base already carries its version (.../v1beta/openai)."""
    base = base.rstrip("/")
    return base + ("/chat/completions" if base.endswith("/openai") else "/v1/chat/completions")


# One pooled client per process: a fresh TLS handshake per request costs a meeting
# answer a few hundred milliseconds.
_SHARED_CLIENT = httpx.Client(verify=tls_context(), timeout=90)


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
        self.client = client or _SHARED_CLIENT

    def _headers(self, prefix: str = "MODEL_GATEWAY") -> dict[str, str]:
        if ref := os.getenv(f"{prefix}_API_KEY_SECRET_VERSION"):
            return {"Authorization": "Bearer " + secret(ref).decode().strip()}
        # Local development only; deployed services read the key from Secret Manager.
        if key := os.getenv(f"{prefix}_API_KEY"):
            return {"Authorization": "Bearer " + key}
        return {}

    def _route(self, index: int) -> tuple[str, dict[str, str]]:
        """The fallback may sit on its own gateway, e.g. a free OpenRouter primary backed by Straitly."""
        prefix = "MODEL_FALLBACK_GATEWAY" if index > 0 and os.getenv(
            "MODEL_FALLBACK_GATEWAY_BASE_URL") else "MODEL_GATEWAY"
        return (_completions_url(os.environ[f"{prefix}_BASE_URL"].rstrip("/")),
                self._headers(prefix))

    def _post(self, url: str, headers: dict, body: dict) -> httpx.Response:
        response = self.client.post(url, headers=headers, json=body)
        if response.status_code == 429:
            # Free model pools rate-limit in short bursts; one quick retry usually lands.
            time.sleep(1)
            response = self.client.post(url, headers=headers, json=body)
        return response

    def complete(self, messages: list[dict], *, model_class: str = "planner") -> Completion:
        failures = []
        for index, model in enumerate(self.models):
            url, headers = self._route(index)
            body = {"model": model, "temperature": 0, "messages": messages}
            if model_class == "planner":
                body["response_format"] = {"type": "json_object"}
            if "generativelanguage.googleapis.com" in url:
                # Gemini thinks by default; keep it to the minimum so a meeting answer isn't kept waiting.
                body["reasoning_effort"] = "minimal"
            elif "openrouter.ai" in url:
                # Reasoning models spend seconds thinking before speaking; a meeting can't wait.
                body["reasoning"] = {"enabled": False}
            try:
                response = self._post(url, headers, body)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                if not content or not content.strip():
                    raise ValueError("Empty completion")
                return Completion(text=content, provider=model)
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                failures.append(f"{model}: {type(exc).__name__}")
        raise ModelUnavailable("All model providers failed: " + ", ".join(failures))


@dataclass
class Streamed:
    """What a streamed turn produced: the text already handed out, and any tool calls."""
    text: str
    tool_calls: list[dict]
    provider: str


def _thinking_off(url: str, body: dict) -> None:
    if "generativelanguage.googleapis.com" in url:
        body["reasoning_effort"] = "minimal"
    elif "openrouter.ai" in url:
        body["reasoning"] = {"enabled": False}


def stream(gateway: "LiteLLMGateway", messages: list[dict], tools: list[dict], on_text) -> Streamed:
    """One streamed call to the primary model with native tool calling.

    Text deltas go to `on_text` as they arrive so speech can start on the first sentence;
    tool calls are collected whole. Only the primary model streams: a fallback after words
    were already spoken would talk over them, so a failure raises before or after and the
    caller decides.
    """
    url, headers = gateway._route(0)
    body = {"model": gateway.models[0], "temperature": 0, "messages": messages, "stream": True}
    if tools:
        body["tools"] = tools
    _thinking_off(url, body)
    text, calls = [], {}
    with gateway.client.stream("POST", url, headers=headers, json=body) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            choices = json.loads(data).get("choices") or []
            delta = (choices[0].get("delta") or {}) if choices else {}
            if piece := delta.get("content"):
                text.append(piece)
                on_text(piece)
            for index, call in enumerate(delta.get("tool_calls") or []):
                slot = calls.setdefault(call.get("index", index), {"name": "", "arguments": ""})
                function = call.get("function") or {}
                slot["name"] += function.get("name") or ""
                slot["arguments"] += function.get("arguments") or ""
    return Streamed("".join(text), [calls[key] for key in sorted(calls)], gateway.models[0])


def json_reply(completion: Completion) -> dict:
    text = completion.text.strip()
    if text.startswith("```"):
        # Small models wrap JSON in a markdown fence even when asked not to.
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Model did not return JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Model did not return a JSON object")
    return value
