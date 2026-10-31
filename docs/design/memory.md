# Memory and query routing

This phase implements the PDF's five-store design: the Phase 3 append-only event log, a temporal Postgres graph, a Qdrant vector index, Postgres summaries, and live connector reads. Counts use structured Postgres rows. Relationship questions use graph edges; recall uses Qwen3 vector search plus Postgres full-text search; period overviews use summaries. The query API returns the chosen route, an answer, and source citations.

## Provisioning

1. Apply migration `005_memory.sql` with `python scripts/migrate.py`. `cue_app` can read the derived tables but cannot write them. `cue_ingest` projects events and writes rollups. Row-level security remains active for both roles.
2. Set `CANONICAL_EVENTS_SUBSCRIPTION` to a pull subscription on the existing `CANONICAL_EVENTS_TOPIC`, then run `python scripts/process_memory.py`. Keep dead-letter handling and retry enabled. The worker checks that every delivery matches its event-log row before projecting it.
3. Run Qdrant, one collection per Cue tenant. Local Compose includes Qdrant on port 6333. In production set `QDRANT_URL` and `QDRANT_API_KEY_SECRET_VERSION`. Collections are created on first write with 1024-dimensional cosine vectors and payload indexes on ACL fields.
4. Run an OpenAI-compatible embedding endpoint serving **`Qwen/Qwen3-Embedding-0.6B`** with 1024-dimensional output. Set `EMBEDDING_BASE_URL` and, if needed, `EMBEDDING_API_KEY_SECRET_VERSION`. A GPU deployment of vLLM can serve this model with `vllm serve Qwen/Qwen3-Embedding-0.6B --runner pooling --port 8001`. [Qwen model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B); [vLLM embedding model support](https://docs.vllm.ai/en/stable/models/pooling_models/embed/).
5. Configure the team's LiteLLM or equivalent OpenAI-compatible gateway at `MODEL_GATEWAY_BASE_URL`, with `MEMORY_SMALL_MODEL` for classification, summarization, and evidence-grounded answers. Keep its API key in Secret Manager through `MODEL_GATEWAY_API_KEY_SECRET_VERSION`.

The worker embeds each new nonempty event once and marks the Postgres projection after Qdrant accepts the point. On a retry it upserts the same deterministic Qdrant point; successfully indexed events do not re-embed. Raw events remain in GCS and are not embedded again for rollups.

## Source identity and permissions

Every memory document, graph edge, and summary retains the source ACL. Query time intersects all participants' principal sets for a shared channel or meeting. A tenant admin's automatic `cue:admins` principal does **not** grant access to personal Gmail or private channels. Public source objects are public only within their Cue tenant.

Provision source memberships with the trusted operator script after verifying them in the vendor:

```sh
python scripts/grant_principal.py TENANT_UUID FIREBASE_UID github:repo:123
python scripts/grant_principal.py TENANT_UUID FIREBASE_UID slack:channel:C123
python scripts/grant_principal.py TENANT_UUID FIREBASE_UID linear:team:TEAM_UUID
python scripts/grant_principal.py TENANT_UUID FIREBASE_UID email:owner:owner@example.com
```

Delegated email grants are checked against the user's verified Firebase email. The other grants require operator verification of vendor membership. To link vendor identities for the same person across tools, use `python scripts/link_identity.py TENANT_UUID FIREBASE_UID github:user:123` (or a Slack, Linear, or Gmail person alias). This links existing and future derived graph records while leaving the source event log immutable.

## Summary jobs

Run `scripts/build_summaries.py` as Cloud Scheduler jobs. Daily summaries are grouped by identical ACL and by all/team/project scope. Week summaries consume days; month summaries consume full weeks plus boundary days; year summaries consume months. Each summary has source-event links in `memory_summary_sources`. Rollups never enter the vector index.

```sh
python scripts/build_summaries.py --period day --start 2026-10-28
python scripts/build_summaries.py --period week --start 2026-10-26
python scripts/build_summaries.py --period month --start 2026-10-01
python scripts/build_summaries.py --period year --start 2026-01-01
```

Schedule the week job after all seven day jobs, the month job after its weeks and boundary days, and the year job after its months. Rerun affected rollups after a late connector reconciliation. `--tenant` limits a run to one tenant.

## Query API

`POST /v1/tenants/{tenant_id}/memory/query` requires a Firebase bearer token and tenant membership. A shared question lists other tenant-member Firebase UIDs in `participants`; the API includes the requester and intersects all principals. Citations contain source event IDs, URLs when a connector supplies them, timestamps, and raw GCS references. GCS references are internal audit pointers, not public downloads.

```json
{"question":"How many PRs merged this week?","participants":[]}
```

Current status is read live from the selected GitHub or Linear connection and requires an explicit target:

```json
{"question":"Is issue 42 open?","target":{"provider":"github","connection_id":"CONNECTION_UUID","owner":"ORG","repo":"REPO","number":42}}
```

For Linear, use `provider`, `connection_id`, and `issue_id`. The live read checks the returned repository or team ACL before showing the result. The model can choose a route and filters, but cannot construct SQL or select a connector token. The endpoint rechecks Qdrant hits against Postgres ACLs before passing evidence to the model.

## Verification and current limits

CI tests migration repeatability, tenant isolation, per-source ACLs, shared-context intersection, Qdrant filtering, projection idempotency, and summary citations. Live Qdrant, Qwen serving, LiteLLM, Firebase identities, and vendor status reads still need deployment credentials to verify end to end. Source membership changes and connector revocation must trigger memory ACL updates or deletion; that lifecycle is part of Phase 8. The answer generator is evidence constrained, but answer quality needs the Phase 8 evaluation harness. Full agent task orchestration and action policy follow in Phase 6.
