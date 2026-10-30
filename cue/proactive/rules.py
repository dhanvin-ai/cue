"""Proactive rule catalog: digests, reminders, stale PRs, and overdue actions."""

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg

from cue.proactive import quiet
from cue.runtime import cron, store

KINDS = {"daily_digest", "weekly_digest", "reminder", "stale_pr", "overdue_action"}
DEFAULT_SCHEDULES = {
    "daily_digest": "30 9 * * *",
    "weekly_digest": "0 16 * * 5",
    "stale_pr": "0 * * * *",
    "overdue_action": "0 * * * *",
}


def create_rule(database: psycopg.Connection, tenant_id: UUID, *, rule_key: str, kind: str,
                owner_uid: str, schedule: str | None = None, timezone_name: str = "UTC",
                config: dict | None = None, next_run_at: datetime | None = None) -> UUID:
    if kind not in KINDS:
        raise ValueError(f"Unsupported proactive rule {kind!r}")
    if store.membership(database, tenant_id, owner_uid) is None:
        raise PermissionError("Rule owner is not a member of this tenant")
    if kind == "reminder":
        if next_run_at is None:
            raise ValueError("Reminders need next_run_at")
        schedule = None
    else:
        schedule = schedule or DEFAULT_SCHEDULES[kind]
        cron.parse(schedule)
    rule_id = uuid4()
    database.execute(
        "INSERT INTO proactive_rules (tenant_id, id, rule_key, kind, schedule, timezone, "
        "owner_uid, config, next_run_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (tenant_id, rule_id, rule_key, kind, schedule, timezone_name, owner_uid,
         json.dumps(config or {}), next_run_at),
    )
    return rule_id


def set_enabled(database: psycopg.Connection, tenant_id: UUID, rule_key: str,
                enabled: bool) -> None:
    changed = database.execute(
        "UPDATE proactive_rules SET enabled = %s WHERE tenant_id = %s AND rule_key = %s",
        (enabled, tenant_id, rule_key),
    ).rowcount
    if not changed:
        raise LookupError("Proactive rule not found")


def all_rules(database: psycopg.Connection, tenant_id: UUID) -> list[dict]:
    """Every rule in the tenant, disabled ones included, for the admin view."""
    rows = database.execute(
        "SELECT id, rule_key, kind, schedule, timezone, owner_uid, config, next_run_at, "
        "enabled, last_run_at FROM proactive_rules WHERE tenant_id = %s "
        "ORDER BY rule_key", (tenant_id,),
    ).fetchall()
    keys = ("id", "rule_key", "kind", "schedule", "timezone", "owner_uid", "config",
            "next_run_at", "enabled", "last_run_at")
    return [dict(zip(keys, row)) for row in rows]


def mutes(database: psycopg.Connection, tenant_id: UUID) -> list[dict]:
    rows = database.execute(
        "SELECT firebase_uid, rule_key, created_at FROM proactive_mutes "
        "WHERE tenant_id = %s ORDER BY created_at DESC", (tenant_id,),
    ).fetchall()
    keys = ("firebase_uid", "rule_key", "created_at")
    return [dict(zip(keys, row)) for row in rows]


def mute(database: psycopg.Connection, tenant_id: UUID, uid: str, rule_key: str = "*") -> None:
    if store.membership(database, tenant_id, uid) is None:
        raise PermissionError("Not a member of this tenant")
    database.execute(
        "INSERT INTO proactive_mutes (tenant_id, firebase_uid, rule_key) VALUES (%s, %s, %s) "
        "ON CONFLICT DO NOTHING", (tenant_id, uid, rule_key),
    )


def unmute(database: psycopg.Connection, tenant_id: UUID, uid: str, rule_key: str = "*") -> None:
    database.execute(
        "DELETE FROM proactive_mutes WHERE tenant_id = %s AND firebase_uid = %s "
        "AND rule_key = %s", (tenant_id, uid, rule_key),
    )


def _muted(database: psycopg.Connection, tenant_id: UUID, uid: str, rule_key: str) -> bool:
    return database.execute(
        "SELECT 1 FROM proactive_mutes WHERE tenant_id = %s AND firebase_uid = %s "
        "AND rule_key IN (%s, '*')", (tenant_id, uid, rule_key),
    ).fetchone() is not None


def _rules(database: psycopg.Connection, tenant_id: UUID) -> list[dict]:
    rows = database.execute(
        "SELECT id, rule_key, kind, schedule, timezone, owner_uid, config, next_run_at "
        "FROM proactive_rules WHERE tenant_id = %s AND enabled AND EXISTS ("
        "SELECT 1 FROM users WHERE users.tenant_id = proactive_rules.tenant_id "
        "AND users.firebase_uid = proactive_rules.owner_uid AND users.revoked_at IS NULL) "
        "ORDER BY rule_key",
        (tenant_id,),
    ).fetchall()
    keys = ("id", "rule_key", "kind", "schedule", "timezone", "owner_uid", "config",
            "next_run_at")
    return [dict(zip(keys, row)) for row in rows]


def _iso(value) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def _content(database: psycopg.Connection, tenant_id: UUID, rule: dict,
             now: datetime) -> str | None:
    kind = rule["kind"]
    if kind == "daily_digest":
        return "Prepare the daily standup digest for the last 24 hours. Cite source events."
    if kind == "weekly_digest":
        return "Prepare the weekly summary for the last 7 days. Cite source events."
    if kind == "reminder":
        return str(rule["config"].get("message") or "Send the scheduled reminder.")
    if kind == "stale_pr":
        cutoff = now - timedelta(hours=48)
        rows = database.execute(
            "SELECT event_id, text, occurred_at FROM memory_documents "
            "WHERE tenant_id = %s AND type LIKE 'pr.%%' AND facts->>'state' = 'open' "
            "AND occurred_at < %s ORDER BY occurred_at LIMIT 20",
            (tenant_id, cutoff),
        ).fetchall()
        if not rows:
            return None
        lines = [f"- {text} ({event_id}, since {when.isoformat()})"
                 for event_id, text, when in rows]
        return ("Flag pull requests waiting on review for more than 48 hours:\n"
                + "\n".join(lines) + "\nCite each source event.")
    if kind == "overdue_action":
        rows = database.execute(
            "SELECT note_id, action_items FROM ("
            "SELECT id AS note_id, action_items FROM meeting_notes WHERE tenant_id = %s) AS notes",
            (tenant_id,),
        ).fetchall()
        overdue = []
        for note_id, items in rows:
            for item in items or []:
                due = _iso(item.get("due"))
                if due is not None and due < now:
                    overdue.append(f"- {item.get('text', 'action')} (due {due.isoformat()}, "
                                   f"note {note_id})")
        if not overdue:
            return None
        return ("Follow up on overdue action items:\n" + "\n".join(overdue[:20])
                + "\nCite each source note.")
    return None


def _run_key(rule: dict, now: datetime) -> str:
    if rule["kind"] == "reminder":
        return f"reminder:{rule['next_run_at'].isoformat()}"
    return f"cron:{now.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M')}"


def _due(rule: dict, now: datetime) -> bool:
    if rule["kind"] == "reminder":
        return rule["next_run_at"] is not None and rule["next_run_at"] <= now
    local = now.astimezone(ZoneInfo(rule["timezone"]))
    return cron.matches(rule["schedule"], local)


def _dispatch(database: psycopg.Connection, tenant_id: UUID, rule: dict, run_id: UUID,
              run_key: str, text: str, now: datetime) -> UUID | None:
    task_id, _ = store.create_task(
        database, tenant_id, source="schedule", requester_uid=rule["owner_uid"],
        request_text=text, idempotency_key=f"proactive:{rule['id']}:{run_key}",
        channel_ref="proactive", thread_ref=rule["rule_key"],
    )
    database.execute(
        "UPDATE proactive_runs SET status = 'dispatched', task_id = %s, updated_at = now() "
        "WHERE tenant_id = %s AND id = %s", (task_id, tenant_id, run_id),
    )
    database.execute(
        "UPDATE proactive_rules SET last_run_at = %s, "
        "next_run_at = CASE WHEN kind = 'reminder' THEN NULL ELSE next_run_at END "
        "WHERE tenant_id = %s AND id = %s", (now, tenant_id, rule["id"]),
    )
    store.audit(database, tenant_id, actor="cue", action="proactive", task_id=task_id,
                decision="dispatched",
                detail={"rule": rule["rule_key"], "kind": rule["kind"]})
    return task_id


def tick(tenant_id: UUID, *, database_url: str | None = None, queue=None,
         now: datetime | None = None) -> list[UUID]:
    """Evaluate rules and release deferred messages. Safe to call every minute."""
    moment = now or datetime.now(timezone.utc)
    dispatched: list[UUID] = []
    with store.tenant_connection(tenant_id, database_url) as database:
        for rule in _rules(database, tenant_id):
            if not _due(rule, moment):
                continue
            if _muted(database, tenant_id, rule["owner_uid"], rule["rule_key"]):
                continue
            run_key = _run_key(rule, moment)
            run_id = uuid4()
            row = database.execute(
                "INSERT INTO proactive_runs (tenant_id, id, rule_id, run_key, status, payload) "
                "VALUES (%s, %s, %s, %s, 'queued', '{}') "
                "ON CONFLICT (tenant_id, rule_id, run_key) DO NOTHING RETURNING id",
                (tenant_id, run_id, rule["id"], run_key),
            ).fetchone()
            if row is None:
                continue
            text = _content(database, tenant_id, rule, moment)
            if text is None:
                database.execute(
                    "UPDATE proactive_runs SET status = 'skipped', updated_at = now() "
                    "WHERE tenant_id = %s AND id = %s", (tenant_id, run_id),
                )
                continue
            release = quiet.deferral(database, tenant_id, rule["owner_uid"], moment)
            if release is not None:
                database.execute(
                    "UPDATE proactive_runs SET status = 'deferred', deliver_after = %s, "
                    "payload = %s, updated_at = now() WHERE tenant_id = %s AND id = %s",
                    (release, json.dumps({"text": text}), tenant_id, run_id),
                )
                store.audit(database, tenant_id, actor="cue", action="proactive",
                            decision="deferred",
                            detail={"rule": rule["rule_key"], "deliver_after": release.isoformat()})
                continue
            task_id = _dispatch(database, tenant_id, rule, run_id, run_key, text, moment)
            if task_id:
                dispatched.append(task_id)

        rows = database.execute(
            "SELECT run.id, run.run_key, run.payload, rule.id, rule.rule_key, rule.kind, rule.schedule, "
            "rule.timezone, rule.owner_uid, rule.config, rule.next_run_at "
            "FROM proactive_runs AS run JOIN proactive_rules AS rule "
            "ON rule.tenant_id = run.tenant_id AND rule.id = run.rule_id "
            "WHERE run.tenant_id = %s AND run.status = 'deferred' "
            "AND run.deliver_after <= %s AND rule.enabled AND EXISTS ("
            "SELECT 1 FROM users WHERE users.tenant_id = rule.tenant_id "
            "AND users.firebase_uid = rule.owner_uid AND users.revoked_at IS NULL) "
            "ORDER BY run.deliver_after",
            (tenant_id, moment),
        ).fetchall()
        keys = ("id", "run_key", "payload", "rule_id", "rule_key", "kind", "schedule",
                "timezone", "owner_uid", "config", "next_run_at")
        for row in rows:
            item = dict(zip(keys, row))
            rule = {"id": item["rule_id"], "rule_key": item["rule_key"], "kind": item["kind"],
                    "schedule": item["schedule"], "timezone": item["timezone"],
                    "owner_uid": item["owner_uid"], "config": item["config"],
                    "next_run_at": item["next_run_at"]}
            text = (item["payload"] or {}).get("text")
            if not text:
                continue
            task_id = _dispatch(database, tenant_id, rule, item["id"], item["run_key"],
                                text, moment)
            if task_id:
                dispatched.append(task_id)
    for task_id in dispatched:
        if queue is not None:
            queue.enqueue(tenant_id, task_id)
    return dispatched


def runs(database: psycopg.Connection, tenant_id: UUID, limit: int = 50) -> list[dict]:
    rows = database.execute(
        "SELECT run.id, rule.rule_key, run.run_key, run.status, run.deliver_after, "
        "run.task_id, run.created_at FROM proactive_runs AS run "
        "JOIN proactive_rules AS rule ON rule.tenant_id = run.tenant_id "
        "AND rule.id = run.rule_id WHERE run.tenant_id = %s "
        "ORDER BY run.created_at DESC LIMIT %s", (tenant_id, limit),
    ).fetchall()
    keys = ("id", "rule_key", "run_key", "status", "deliver_after", "task_id", "created_at")
    return [dict(zip(keys, row)) for row in rows]
