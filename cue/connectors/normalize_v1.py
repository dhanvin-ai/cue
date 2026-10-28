"""Permission-bearing canonical events for the additional v1 sources."""

from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Mapping, Any
from uuid import UUID

from cue.connectors.base import AccessControl, CanonicalEvent


def _time(value: str | None) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else datetime.now(timezone.utc)


def normalize(source: str, raw: Mapping[str, Any], tenant_id: UUID) -> CanonicalEvent:
    if source == "gmail":
        item, owner = raw["message"], raw["mailbox"].casefold()
        headers = {h["name"].lower(): h["value"] for h in item.get("payload", {}).get("headers", [])}
        return CanonicalEvent(
            tenant_id, f"gmail:{owner}:{item['id']}:{item.get('historyId', '0')}", source,
            "mail.message", datetime.fromtimestamp(int(item["internalDate"]) / 1000, timezone.utc),
            (f"gmail:person:{parseaddr(headers['from'])[1].casefold()}",) if "from" in headers else (),
            (f"gmail:message:{item['id']}", f"gmail:thread:{item['threadId']}"),
            f"{headers.get('subject', '')}\n{item.get('snippet', '')}",
            AccessControl("restricted", (f"email:owner:{owner}",)),
        )
    if source == "calendar":
        item, owner = raw["event"], raw["owner"]
        attendees = {a["email"] for a in item.get("attendees", []) if a.get("email")}
        attendees.add(owner)
        return CanonicalEvent(
            tenant_id, f"calendar:{owner}:{item['id']}:{item.get('etag', item.get('updated', ''))}",
            source, f"calendar.{item.get('status', 'confirmed')}", _time(item.get("updated") or item.get("created")),
            (f"gmail:person:{item['organizer']['email']}",) if item.get("organizer", {}).get("email") else (),
            (f"calendar:event:{item['id']}", f"calendar:calendar:{raw['calendar_id']}"),
            f"{item.get('summary', '')}\n{item.get('description', '')}",
            AccessControl("restricted", tuple(f"email:owner:{a}" for a in sorted(attendees))),
        )
    if source == "slack":
        item = raw["event"]
        if item.get("subtype") == "message_changed":
            item = {**item["message"], "channel": item["channel"]}
        channel = item["channel"]
        ts = item.get("ts") or item.get("event_ts")
        return CanonicalEvent(
            tenant_id, f"slack:{raw['team_id']}:{channel}:{ts}", source, "slack.message",
            datetime.fromtimestamp(float(ts), timezone.utc),
            (f"slack:person:{item['user']}",) if item.get("user") else (),
            (f"slack:message:{channel}:{ts}", f"slack:channel:{channel}"),
            item.get("text", ""),
            AccessControl("restricted", (f"slack:channel:{channel}",)),
        )
    if source == "linear":
        item = raw["data"]
        team_id = item.get("teamId") or (item.get("team") or {}).get("id")
        project_id = item.get("projectId") or (item.get("project") or {}).get("id")
        org_id = raw["organizationId"]
        assignee = item.get("assignee") or {}
        owner_id = item.get("assigneeId") or assignee.get("id")
        facts = {"state": (item.get("state") or {}).get("name")}
        if "assignee" in item or "assigneeId" in item:
            facts["owner_alias"] = f"linear:person:{owner_id}" if owner_id else None
            facts["owner_label"] = assignee.get("name")
        return CanonicalEvent(
            tenant_id, f"linear:{item['id']}:{item.get('updatedAt', raw.get('createdAt', ''))}",
            source, f"linear.{raw.get('type', 'Issue').lower()}.{raw.get('action', 'snapshot')}",
            _time(item.get("updatedAt") or raw.get("createdAt")),
            (f"linear:person:{raw['actor']['id']}",) if raw.get("actor") and raw["actor"].get("id") else (),
            (f"linear:issue:{item['id']}",) + ((f"linear:team:{team_id}",) if team_id else ()) +
            ((f"linear:project:{project_id}",) if project_id else ()),
            f"{item.get('title', '')}\n{item.get('description') or item.get('body') or ''}\n{(item.get('state') or {}).get('name', '')}\n{assignee.get('name') or ''}",
            AccessControl("restricted", (f"linear:team:{team_id}",) if team_id else (f"linear:org:{org_id}:admins",)),
            facts=facts,
        )
    if source == "recall":
        data = raw["data"]
        bot = data.get("bot") or {}
        bot_id = bot.get("id") or data.get("bot_id")
        transcript = data.get("transcript") or {}
        words = transcript.get("words") or []
        attendees = bot.get("metadata", {}).get("attendees") or []
        principals = tuple(f"email:owner:{email}" for email in attendees)
        return CanonicalEvent(
            tenant_id, f"recall:{bot_id}:{raw['event']}:{transcript.get('original_transcript_id', transcript.get('segment_index', data.get('data', {}).get('updated_at', '')))}",
            source, raw["event"], _time(transcript.get("occurred_at") or data.get("data", {}).get("updated_at")),
            (f"recall:person:{transcript['speaker_id']}",) if transcript.get("speaker_id") is not None else (),
            (f"recall:meeting:{bot_id}",),
            " ".join(word.get("text", "") for word in words),
            AccessControl("restricted", principals or ("cue:admins",)),
        )
    raise ValueError(f"Unsupported source: {source}")
