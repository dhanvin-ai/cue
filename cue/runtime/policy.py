"""Risk tiers from the architecture PDF (page 10) applied to every tool call.

Tier 0 read: runs freely within the asker's permissions.
Tier 1 internal and reversible: runs automatically, logged.
Tier 2 internal but visible to others: requester confirms with one click.
Tier 3 external: draft plus explicit approval, every time in v1.
Tier 4 prohibited: never available to the agent.

Tenant admins may widen tiers 0-2 per tier, tool, or person. Tier 3 cannot be
widened in v1 and tier 4 can never run.
"""

from dataclasses import dataclass

import psycopg

READ = 0
INTERNAL_REVERSIBLE = 1
INTERNAL_VISIBLE = 2
EXTERNAL = 3
PROHIBITED = 4

TIERS = {
    READ: "read",
    INTERNAL_REVERSIBLE: "internal reversible",
    INTERNAL_VISIBLE: "internal visible",
    EXTERNAL: "external",
    PROHIBITED: "prohibited",
}

DEFAULT_MODES = {
    READ: "auto",
    INTERNAL_REVERSIBLE: "auto",
    INTERNAL_VISIBLE: "approve",
    EXTERNAL: "approve",
    PROHIBITED: "deny",
}

# Admin overrides cannot widen these tiers. The PDF fixes them for v1.
LOCKED = {EXTERNAL, PROHIBITED}


@dataclass(frozen=True)
class Decision:
    tier: int
    mode: str
    reason: str

    @property
    def automatic(self) -> bool:
        return self.mode == "auto"

    @property
    def forbidden(self) -> bool:
        return self.mode == "deny"


def decide(database: psycopg.Connection, tenant_id, tool: str, tier: int, actor: str) -> Decision:
    if tier not in TIERS:
        raise ValueError(f"Unknown risk tier {tier}")
    if tier == PROHIBITED:
        return Decision(tier, "deny", "Tier 4 actions are prohibited")
    if tier == EXTERNAL:
        return Decision(tier, "approve", "Tier 3 actions need explicit approval every time")

    row = database.execute(
        "SELECT scope, mode FROM agent_policies WHERE tenant_id = %s AND ("
        "(scope = 'person' AND subject = %s) OR (scope = 'tool' AND subject = %s) "
        "OR (scope = 'tier' AND subject = %s)) "
        "ORDER BY CASE scope WHEN 'person' THEN 0 WHEN 'tool' THEN 1 ELSE 2 END LIMIT 1",
        (tenant_id, actor, tool, str(tier)),
    ).fetchone()
    if row is None:
        return Decision(tier, DEFAULT_MODES[tier], f"default for tier {tier}")
    return Decision(tier, row[1], f"tenant override for {row[0]}")
