from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Protocol
from uuid import UUID


@dataclass(frozen=True)
class AccessControl:
    visibility: str
    principals: tuple[str, ...]


@dataclass(frozen=True)
class CanonicalEvent:
    tenant_id: UUID
    event_id: str
    source: str
    type: str
    occurred_at: datetime
    actors: tuple[str, ...]
    objects: tuple[str, ...]
    text: str
    acl: AccessControl
    facts: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Tool:
    name: str
    risk_tier: int


class Connector(Protocol):
    provider: str

    def authorize(self, external_id: str) -> None: ...

    def backfill(self, external_id: str, since: datetime) -> Iterable[Mapping[str, Any]]: ...

    def subscribe(self) -> None: ...

    def normalize(self, raw: Mapping[str, Any], tenant_id: UUID) -> CanonicalEvent: ...

    def acl(self, raw: Mapping[str, Any]) -> AccessControl: ...

    def tools(self) -> tuple[Tool, ...]: ...
