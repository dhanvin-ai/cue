"""ACL-preserving day, week, month, and year rollups with event citations."""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, NAMESPACE_URL, uuid5

import psycopg

from cue.memory.model import SmallModel

CHILD = {"week": "day", "month": "week", "year": "month"}


def _end(period: str, start: date) -> date:
    if period == "day":
        return start + timedelta(days=1)
    if period == "week":
        return start + timedelta(days=7)
    if period == "month":
        return date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    if period == "year":
        return date(start.year + 1, 1, 1)
    raise ValueError("Unsupported summary period")


def _aligned(period: str, start: date) -> bool:
    return period == "day" or (period == "week" and start.weekday() == 0) or (
        period == "month" and start.day == 1) or (
        period == "year" and start.month == 1 and start.day == 1)


def _compress(model: SmallModel, texts: list[str], period: str) -> str:
    current = [value[:4000] for value in texts if value.strip()]
    if not current:
        return "No descriptive text was recorded."
    while len(current) > 100:
        current = [model.summarize(current[index:index + 100], period=period)
                   for index in range(0, len(current), 100)]
    return model.summarize(current, period=period)


def run_rollup(tenant_id: UUID, period: str, start: date, database_url: str,
               model: SmallModel | None = None) -> int:
    if period not in {"day", "week", "month", "year"} or not _aligned(period, start):
        raise ValueError("Summary period start is not aligned")
    end = _end(period, start)
    grouped: dict[tuple[str, tuple[str, ...], str], dict] = defaultdict(
        lambda: {"texts": [], "event_ids": set()}
    )
    with psycopg.connect(database_url) as database:
        database.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
        if period == "day":
            rows = database.execute(
                "SELECT event_id, text, visibility, principals, objects FROM memory_documents "
                "WHERE occurred_at >= %s AND occurred_at < %s",
                (datetime.combine(start, datetime.min.time(), timezone.utc),
                 datetime.combine(end, datetime.min.time(), timezone.utc)),
            ).fetchall()
            for event_id, text, visibility, principals, objects in rows:
                scopes = {"all"} | {item for item in objects if item.split(":", 1)[0] in {"team", "project"}}
                for scope in scopes:
                    entry = grouped[(visibility, tuple(sorted(principals)), scope)]
                    entry["texts"].append(text)
                    entry["event_ids"].add(event_id)
        else:
            ranges = [(CHILD[period], start, end)]
            if period == "month":
                first_monday = start + timedelta(days=(7 - start.weekday()) % 7)
                full_week_end = first_monday + timedelta(days=((end - first_monday).days // 7) * 7)
                ranges = [("week", first_monday, full_week_end),
                          ("day", start, first_monday), ("day", full_week_end, end)]
            for child, lower, upper in ranges:
                if lower >= upper:
                    continue
                rows = database.execute(
                    "SELECT summary.id, summary.text, summary.visibility, summary.principals, "
                    "summary.scope, array_agg(source.event_id) FROM memory_summaries AS summary "
                    "JOIN memory_summary_sources AS source ON source.tenant_id = summary.tenant_id "
                    "AND source.summary_id = summary.id WHERE summary.period = %s "
                    "AND summary.period_start >= %s AND summary.period_start < %s "
                    "GROUP BY summary.id, summary.text, summary.visibility, summary.principals, summary.scope",
                    (child, lower, upper),
                ).fetchall()
                for _, text, visibility, principals, scope, event_ids in rows:
                    entry = grouped[(visibility, tuple(sorted(principals)), scope)]
                    entry["texts"].append(text)
                    entry["event_ids"].update(event_ids)
    model = model or SmallModel()
    for (visibility, principals, scope), entry in grouped.items():
        summary = _compress(model, entry["texts"], period)
        summary_id = uuid5(NAMESPACE_URL, f"cue:{tenant_id}:{period}:{start}:{scope}:{visibility}:{principals}")
        with psycopg.connect(database_url) as database:
            database.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
            database.execute(
                "INSERT INTO memory_summaries (tenant_id, id, period, period_start, scope, visibility, "
                "principals, text, event_count) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (tenant_id, id) DO UPDATE SET text = EXCLUDED.text, "
                "event_count = EXCLUDED.event_count, created_at = now()",
                (tenant_id, summary_id, period, start, scope, visibility, list(principals), summary,
                 len(entry["event_ids"])),
            )
            database.execute("DELETE FROM memory_summary_sources WHERE tenant_id = %s AND summary_id = %s",
                             (tenant_id, summary_id))
            with database.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO memory_summary_sources (tenant_id, summary_id, event_id) VALUES (%s, %s, %s)",
                    [(tenant_id, summary_id, event_id) for event_id in sorted(entry["event_ids"])],
                )
    return len(grouped)
