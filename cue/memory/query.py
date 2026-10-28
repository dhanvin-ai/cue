"""Route questions through ACL-filtered structured, graph, vector, and summary stores."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import psycopg

from cue.connectors.factory import make_connector
from cue.memory.model import QueryPlan, SmallModel
from cue.memory.vector import QdrantIndex, QwenEmbedder

ALLOWED = "(visibility = 'public' OR principals && %s::text[])"
DOCUMENT = "event_id, source, type, text, raw_ref, source_url, occurred_at, objects"


def _citation(row: tuple, number: int) -> dict:
    event_id, source, kind, text, raw_ref, source_url, occurred_at, objects = row
    return {"number": number, "event_id": event_id, "source": source, "type": kind,
            "source_object": objects[0] if objects else None, "url": source_url,
            "raw_ref": raw_ref, "occurred_at": occurred_at.isoformat(), "text": text}


def _principals(database: psycopg.Connection, tenant_id: UUID, requester: str,
                participants: list[str]) -> set[str]:
    members = list(dict.fromkeys([requester, *participants]))
    if len(members) > 20:
        raise ValueError("A shared query supports at most 20 participants")
    effective = None
    for uid in members:
        row = database.execute(
            "SELECT role FROM users WHERE tenant_id = %s AND firebase_uid = %s",
            (tenant_id, uid),
        ).fetchone()
        if row is None:
            raise PermissionError("Every participant must be a tenant member")
        grants = {principal for (principal,) in database.execute(
            "SELECT principal FROM user_principals WHERE tenant_id = %s AND firebase_uid = %s",
            (tenant_id, uid),
        ).fetchall()}
        if row[0] == "admin":
            grants.add("cue:admins")
        effective = grants if effective is None else effective & grants
    return effective or set()


def _keyword(database: psycopg.Connection, question: str, principals: set[str], limit: int) -> list[tuple]:
    return database.execute(
        f"SELECT {DOCUMENT} FROM memory_documents WHERE {ALLOWED} "
        "AND search_vector @@ websearch_to_tsquery('english', %s) "
        "ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('english', %s)) DESC, occurred_at DESC "
        "LIMIT %s",
        (sorted(principals), question, question, limit),
    ).fetchall()


def _authorized_documents(database: psycopg.Connection, ids: list[str],
                          principals: set[str]) -> dict[str, tuple]:
    if not ids:
        return {}
    rows = database.execute(
        f"SELECT {DOCUMENT} FROM memory_documents WHERE event_id = ANY(%s) AND {ALLOWED}",
        (ids, sorted(principals)),
    ).fetchall()
    return {row[0]: row for row in rows}


def _hybrid(database: psycopg.Connection, tenant_id: UUID, question: str,
            principals: set[str], embedder: QwenEmbedder, index: QdrantIndex) -> list[tuple]:
    keyword = _keyword(database, question, principals, 30)
    vector_ids = index.search(tenant_id, embedder.embed(question, query=True), principals, 30)
    scores = defaultdict(float)
    for rank, row in enumerate(keyword):
        scores[row[0]] += 1 / (60 + rank + 1)
    for rank, event_id in enumerate(vector_ids):
        scores[event_id] += 1 / (60 + rank + 1)
    authorized = _authorized_documents(database, list(scores), principals)
    return [authorized[event_id] for event_id in sorted(authorized, key=lambda key: scores[key], reverse=True)[:10]]


def _count(database: psycopg.Connection, plan: QueryPlan, principals: set[str]) -> tuple[int, list[tuple]]:
    filters = [ALLOWED]
    params: list[Any] = [sorted(principals)]
    if plan.source:
        filters.append("source = %s")
        params.append(plan.source)
    if plan.event_type:
        filters.append("type = %s")
        params.append(plan.event_type)
    if plan.since:
        filters.append("occurred_at >= %s")
        params.append(plan.since)
    if plan.until:
        filters.append("occurred_at < %s")
        params.append(plan.until)
    where = " AND ".join(filters)
    number = database.execute(
        f"SELECT count(DISTINCT COALESCE(objects[1], event_id)) FROM memory_documents WHERE {where}",
        params,
    ).fetchone()[0]
    examples = database.execute(
        f"SELECT {DOCUMENT} FROM memory_documents WHERE {where} ORDER BY occurred_at DESC LIMIT 5",
        params,
    ).fetchall()
    return number, examples


def _ownership(database: psycopg.Connection, question: str, plan: QueryPlan,
               principals: set[str]) -> list[tuple]:
    seeds = _keyword(database, plan.search_query or question, principals, 5)
    targets = [row[7][0] for row in seeds if row[7]]
    if not targets:
        return []
    relation = plan.relation or "worked_on"
    time_clause = ""
    time_params: list[Any] = []
    if relation == "owned_by":
        as_of = (plan.until - timedelta(microseconds=1)) if plan.until else datetime.now(timezone.utc)
        time_clause = "AND edge.valid_from <= %s AND (edge.valid_to IS NULL OR edge.valid_to > %s) "
        time_params = [as_of, as_of]
    else:
        if plan.since:
            time_clause += "AND edge.valid_from >= %s "
            time_params.append(plan.since)
        if plan.until:
            time_clause += "AND edge.valid_from < %s "
            time_params.append(plan.until)
    rows = database.execute(
        f"SELECT {', '.join('doc.' + column.strip() for column in DOCUMENT.split(','))}, "
        "edge.target_label, edge.target, edge.source_entity "
        "FROM memory_edges AS edge JOIN memory_documents AS doc "
        "ON doc.tenant_id = edge.tenant_id AND doc.event_id = edge.event_id "
        "WHERE edge.predicate = %s AND " +
        ("edge.source_entity = ANY(%s) " if relation == "owned_by" else "edge.target = ANY(%s) ") +
        time_clause +
        "AND (edge.visibility = 'public' OR edge.principals && %s::text[]) "
        "AND (doc.visibility = 'public' OR doc.principals && %s::text[]) "
        "ORDER BY edge.valid_from DESC LIMIT 10",
        (relation, targets, *time_params, sorted(principals), sorted(principals)),
    ).fetchall()
    return [row[:3] + (row[3] + (f"\nOwner: {row[8] or row[9]}" if relation == "owned_by" else
                                f"\nContributor: {row[10]}"),) + row[4:8] for row in rows]


def _period(database: psycopg.Connection, plan: QueryPlan, principals: set[str]) -> list[dict]:
    period = plan.period or "week"
    filters = ["period = %s", "scope = 'all'", ALLOWED]
    params: list[Any] = [period, sorted(principals)]
    if plan.since:
        filters.append("period_start >= %s")
        params.append(plan.since.date())
    if plan.until:
        filters.append("period_start < %s")
        params.append(plan.until.date())
    rows = database.execute(
        "SELECT id, period_start, text, event_count FROM memory_summaries WHERE " +
        " AND ".join(filters) + " ORDER BY period_start DESC LIMIT 4",
        params,
    ).fetchall()
    result = []
    for summary_id, start, text, count in rows:
        sources = database.execute(
            f"SELECT {', '.join('doc.' + column.strip() for column in DOCUMENT.split(','))} "
            "FROM memory_summary_sources AS link JOIN memory_documents AS doc "
            "ON doc.tenant_id = link.tenant_id AND doc.event_id = link.event_id "
            "WHERE link.summary_id = %s AND "
            "(doc.visibility = 'public' OR doc.principals && %s::text[]) "
            "ORDER BY doc.occurred_at DESC LIMIT 10",
            (summary_id, sorted(principals)),
        ).fetchall()
        result.append({"period": period, "start": start.isoformat(), "text": text,
                       "event_count": count, "sources": sources})
    return result


def _live_status(database: psycopg.Connection, tenant_id: UUID, principals: set[str],
                 target: dict | None) -> dict:
    if not target or target.get("provider") not in {"github", "linear"}:
        raise ValueError("Current status needs a GitHub or Linear target")
    connection_id = UUID(target["connection_id"])
    row = database.execute(
        "SELECT provider, external_id, secret_ref FROM connector_connections "
        "WHERE tenant_id = %s AND id = %s AND status = 'active'",
        (tenant_id, connection_id),
    ).fetchone()
    if row is None or row[0] != target["provider"]:
        raise PermissionError("Connector is not available to this tenant")
    provider, external_id, secret_ref = row
    connector = make_connector(provider, external_id, secret_ref)
    if provider == "github":
        owner, repo, number = target["owner"], target["repo"], int(target["number"])
        repository, issue = connector.read_issue(external_id, owner, repo, number)
        if repository["private"] and f"github:repo:{repository['id']}" not in principals:
            raise PermissionError("Requester cannot read this repository")
        return {"answer": f"{issue['title']}: {issue['state']}", "citations": [
            {"number": 1, "source": "github", "url": issue.get("html_url"),
             "source_object": f"github:issue:{issue['id']}"}]}
    issue = connector.read_issue(target["issue_id"])
    team_id = issue["team"]["id"]
    if f"linear:team:{team_id}" not in principals and f"linear:org:{external_id}:admins" not in principals:
        raise PermissionError("Requester cannot read this Linear team")
    return {"answer": f"{issue['title']}: {issue['state']['name']}", "citations": [
        {"number": 1, "source": "linear", "url": issue.get("url"),
         "source_object": f"linear:issue:{issue['id']}"}]}


def query_memory(tenant_id: UUID, requester: str, question: str, participants: list[str],
                 database_url: str, target: dict | None = None, model: SmallModel | None = None,
                 index: QdrantIndex | None = None, embedder: QwenEmbedder | None = None) -> dict:
    model = model or SmallModel()
    plan = model.route(question)
    with psycopg.connect(database_url) as database:
        database.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
        principals = _principals(database, tenant_id, requester, participants)
        if plan.route == "status":
            return {"route": "status", **_live_status(database, tenant_id, principals, target)}
        if plan.route == "count":
            number, rows = _count(database, plan, principals)
            return {"route": "count", "answer": str(number),
                    "citations": [_citation(row, index + 1) for index, row in enumerate(rows)]}
        if plan.route == "period":
            summaries = _period(database, plan, principals)
            evidence = [{"number": index + 1, "text": item["text"],
                         "period": item["period"], "start": item["start"]}
                        for index, item in enumerate(summaries)]
            citations = [{"number": index + 1, "summary_start": item["start"],
                          "sources": [_citation(row, n + 1) for n, row in enumerate(item["sources"])]}
                         for index, item in enumerate(summaries)]
        else:
            rows = (_ownership(database, question, plan, principals) if plan.route == "ownership"
                    else _hybrid(database, tenant_id, question, principals,
                                 embedder or QwenEmbedder(), index or QdrantIndex()))
            citations = [_citation(row, index + 1) for index, row in enumerate(rows)]
            evidence = [{"number": item["number"], "text": item["text"],
                         "source": item["source"], "occurred_at": item["occurred_at"]}
                        for item in citations]
    answer = model.answer(question, evidence) if evidence else "No accessible evidence found."
    return {"route": plan.route, "answer": answer, "citations": citations}
