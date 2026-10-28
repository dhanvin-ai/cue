"""Tool execution with per-call idempotency and a typed registry."""

from dataclasses import dataclass, field
from typing import Any, Callable

import psycopg

from cue.runtime import store
from cue.runtime.planner import ToolCall


class ToolFailed(RuntimeError):
    """A tool raised; the task may retry or fail."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    tier: int
    handler: Callable[[dict], Any] | None = None
    description: str = field(default="")


class ToolRegistry:
    def __init__(self, tools: list[ToolSpec] | None = None):
        self._tools: dict[str, ToolSpec] = {}
        for tool in tools or []:
            self.add(tool)

    def add(self, tool: ToolSpec) -> None:
        if tool.tier not in range(5):
            raise ValueError(f"Tool {tool.name} has an invalid risk tier")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def catalog(self) -> list[dict]:
        return [{"name": tool.name, "tier": tool.tier, "description": tool.description}
                for tool in self._tools.values()]


def run_tool(database: psycopg.Connection, tenant_id, task_id, index: int, call: ToolCall,
             spec: ToolSpec) -> tuple[Any, bool]:
    """Execute a tool call once. Returns (result, reused_from_previous_attempt)."""
    key = store.call_key(index, call.name, call.arguments)
    cached, stored = store.claim_tool_run(database, tenant_id, task_id, key, call.name)
    if cached:
        return stored, True
    if spec.handler is None:
        store.finish_tool_run(database, tenant_id, task_id, key, "failed")
        raise ToolFailed(f"No handler is registered for {call.name}")
    try:
        result = spec.handler(call.arguments)
    except Exception as exc:  # noqa: BLE001 - tool failures are task data
        store.finish_tool_run(database, tenant_id, task_id, key, "failed")
        raise ToolFailed(f"{call.name} failed: {type(exc).__name__}") from exc
    store.finish_tool_run(database, tenant_id, task_id, key, "completed", result)
    return result, False
