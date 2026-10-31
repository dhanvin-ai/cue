# Testing

```sh
pytest -q                 # everything (needs Postgres and Qdrant running)
pytest -q tests/e2e       # end-to-end API journeys only
```

CI (`.github/workflows/tests.yml`) runs the backend suites, then the end-to-end suite, against
Postgres and Qdrant service containers.

## Suites

| File | Covers |
|---|---|
| `test_foundation.py` | auth, tenancy, row-level security |
| `test_github_connector.py` | GitHub App auth, webhooks, backfill |
| `test_ingestion.py` | raw to canonical events, deduplication, outbox, replay |
| `test_vendor_connectors.py` | Gmail, Calendar, Slack, Linear, Recall adapters and signatures |
| `test_memory.py` | projection, ACL intersection, query routing, summaries |
| `test_agent_runtime.py` | planner, policy tiers, approvals, retries, audit |
| `test_meetings.py` | turns, addressing, speaker mapping, interruption, notes |
| `test_pilot_controls.py` | proactive rules, quiet hours, kill switches, revocation, reconciliation, isolation |
| `test_attendee.py`, `test_bolna.py`, `test_tools.py`, … | voice paths, connector tools, and the remaining units |

## End-to-end

`tests/e2e` uses Playwright's API client (no browser needed) to send real HTTP requests to a local
Uvicorn server. Postgres roles and Qdrant are real. The journey covers:

- health checks, authentication and tenant membership;
- signed webhook acceptance and rejection;
- ingestion and deduplication;
- memory projection and indexing;
- count and recall queries with citations;
- participant ACL intersection;
- cross-tenant denial.

Firebase, GCS, Pub/Sub and the model and embedding endpoints are replaced by deterministic local
doubles, because CI has no vendor credentials. Interoperability with live vendors is verified
manually with the local stack in [setup/SETUP.md](../setup/SETUP.md).
