# Phase 1–5 end-to-end verification

Run `pytest -q tests/e2e` after the [local setup](../README.md) starts Postgres and Qdrant, applies migrations, and exports the `.env` values. CI runs these tests separately after the Phase 1–5 suite.

The Playwright Python API client sends real HTTP requests to a local Uvicorn server. The main journey covers health, bearer authentication, tenant membership, signed GitHub webhook rejection and acceptance, raw event routing and deduplication, GCS archive call, canonical outbox publication, Postgres memory projection, Qdrant indexing, count and recall queries, participant ACL intersection, daily summaries, citations, and cross-tenant denial. A second Playwright test checks valid and tampered Slack, Linear, Recall, and Calendar webhook requests.

The test uses real Postgres roles and Qdrant. Firebase token verification, GCS, Pub/Sub, and the LiteLLM/embedding endpoints use local deterministic doubles because CI has no vendor credentials or deployed services. Gmail and Calendar backfill, connector vendor clients, tool writes, graph ownership, and other memory routes remain covered by the Phase 1–5 tests. This suite does not establish interoperability with live vendor systems or browser UI behavior; Cue has no frontend yet. Playwright's API testing mode needs no browser installation.
