# Memory and query routing

Canonical events are projected into four stores, and each kind of question goes to the store that
answers it best:

| Question | Store |
|---|---|
| Counts ("how many PRs merged this week?") | structured Postgres rows |
| Ownership and relationships | temporal graph edges in Postgres |
| Recall ("what did we decide about pricing?") | Qdrant vectors plus Postgres full-text search |
| Period overviews | daily, weekly, monthly and yearly summaries |
| Current status ("is issue 42 open?") | a live read from GitHub or Linear |

Every answer returns its route and citations: source event IDs, URLs, timestamps, and internal GCS
references.

## Provisioning

1. The `cue_ingest` role writes the derived tables. `cue_app` can only read them. Row-level
   security applies to both roles.
2. Point `CANONICAL_EVENTS_SUBSCRIPTION` at the canonical topic and run
   `python scripts/process_memory.py`. It checks every delivery against the event log before it
   projects anything.
3. Run Qdrant (`QDRANT_URL`, and `QDRANT_API_KEY_SECRET_VERSION` in production). Each tenant gets
   one collection, created on first write: 1024-dimensional cosine vectors with indexes on the ACL
   fields.
4. Serve `Qwen/Qwen3-Embedding-0.6B` (1024 dimensions) on an OpenAI-compatible endpoint at
   `EMBEDDING_BASE_URL`. For example: `vllm serve Qwen/Qwen3-Embedding-0.6B --runner pooling --port 8001`.
   Without one, set `CUE_VECTOR_SEARCH=off` for keyword-only recall.
5. Set `MEMORY_SMALL_MODEL` on the model gateway. It handles classification, summaries and
   evidence-grounded answers.

Each event is embedded once. Retries upsert the same deterministic point, and summaries are never
embedded.

## Permissions

Every document, edge and summary keeps its source ACL. For a shared question
(`participants` lists other members), Cue intersects all participants' principals. A tenant
admin's `cue:admins` principal does **not** open personal mailboxes or private channels. Qdrant
hits are rechecked against Postgres ACLs before the model sees them. The model chooses a route and
filters, but it never writes SQL or picks a connector token.

Grant source memberships after verifying them in the vendor tool:

```sh
python scripts/grant_principal.py TENANT FIREBASE_UID github:repo:123
python scripts/grant_principal.py TENANT FIREBASE_UID slack:channel:C123
python scripts/grant_principal.py TENANT FIREBASE_UID linear:team:TEAM_UUID
python scripts/grant_principal.py TENANT FIREBASE_UID email:owner:owner@example.com
python scripts/link_identity.py   TENANT FIREBASE_UID github:user:123
```

An email grant must match the user's verified Firebase email.

## Summaries

```sh
python scripts/build_summaries.py --period day   --start 2026-10-28
python scripts/build_summaries.py --period week  --start 2026-10-26
python scripts/build_summaries.py --period month --start 2026-10-01
python scripts/build_summaries.py --period year  --start 2026-01-01
```

Each summary is built from the level below it:

- days come from events, grouped by identical ACL and by scope (all, team, project);
- weeks come from days;
- months come from full weeks plus the days at either boundary;
- years come from months.

Schedule each level after the one it consumes, and rerun the affected levels after a late
reconciliation. Every summary links to its source events in `memory_summary_sources`.

## Query API

`POST /v1/tenants/{t}/memory/query`

```json
{"question": "How many PRs merged this week?", "participants": []}
```

```json
{"question": "Is issue 42 open?",
 "target": {"provider": "github", "connection_id": "UUID", "owner": "ORG", "repo": "REPO", "number": 42}}
```

For Linear, the target takes `provider`, `connection_id` and `issue_id`. A live read checks the
repository or team ACL before it returns anything.
