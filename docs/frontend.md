# Teammate console (frontend)

`GET /ui` serves a single-page console for the Cue backend: chat with the agent,
read memory answers with citations, decide on approvals, and inspect pilot
controls. It is plain HTML, CSS and JavaScript in `cue/static/` — no build step,
no package manager, no CDN. The API returns it directly, so there is nothing to
deploy separately.

The console is a development and evaluation surface, not the product UI. It is
wired to the same tenant-scoped endpoints a real client would use, so anything
you can do here the backend genuinely supports.

## What each tab covers

| Tab | Endpoints | Needs running |
| --- | --- | --- |
| Ask Cue | `POST /agent/requests`, `GET /agent/tasks/{id}`, `POST /agent/tasks/{id}/requeue` | worker + model gateway |
| Approvals | `GET /agent/approvals`, `POST /agent/approvals/{id}` | worker |
| Memory | `POST /memory/query` | model gateway + embedder + Qdrant |
| Tasks | `GET /agent/tasks?status=&limit=` | worker (to move off `queued`) |
| Meetings | `POST /meetings`, `GET /meetings/{id}/notes`, `POST /meetings/{id}/end` | Recall service |
| Proactive | `GET /proactive`, `POST /proactive/rules`, quiet hours, mutes | scheduler |
| Admin | `/status`, `/admin/access-report`, `/admin/audit/export`, kill switches, revocations | — |

Two things the console shows that are worth knowing about while judging results:

- A **runtime banner** at the top reports whether a model gateway URL and API key
  are configured, and whether a worker is picking tasks up. Without both, tasks
  stay `queued` and memory queries fail; the banner says so instead of leaving
  you staring at a spinner.
- A task left `queued` past its dispatch deadline is flagged as **stranded** with
  a *Requeue* button. Dispatch state lives in Postgres, so if the worker was down
  when Cloud Tasks fired, the task would otherwise never run.

## Running it locally

Postgres and Qdrant must be reachable. With Docker:

```sh
docker compose up -d db qdrant
python scripts/migrate.py && python scripts/ensure_partitions.py
```

The console depends on the dev auth bypass (`CUE_DEV_AUTH_UID`), which makes
`/ui` return 404 when unset. Point it at your local tenant and role:

```sh
# .env
CUE_DEV_AUTH_UID=dev-local-user
CUE_DEV_TENANT_ID=11111111-1111-1111-1111-111111111111
MODEL_GATEWAY_BASE_URL=https://api.straitly.ai   # OpenAI-compatible
MODEL_GATEWAY_API_KEY=<your key>                 # local dev only
```

Then start the API and a worker in two terminals:

```sh
set -a; . ./.env; set +a
uvicorn cue.main:app --port 8000
python scripts/run_local_worker.py --tenant "$CUE_DEV_TENANT_ID"
```

Open <http://127.0.0.1:8000/ui>.

`scripts/run_tasks.py` is the production-shaped worker and registers no tool
handlers, so tasks plan but execute nothing. `run_local_worker.py` is the dev
worker: it registers `memory.query` (tier 0, read-only) and a sample tier 2
`linear.create_issue` so the approval path can actually be exercised. It reads
credentials from the environment only and is not deployed.

## What works without credentials

Everything except inference. Memory retrieval, approvals, status, audit export,
kill switches, quiet hours and proactive rules all run against real data. Ask and
Memory need `MODEL_GATEWAY_API_KEY`; meetings need a live Recall integration.
With the key absent the banner explains it, and failures surface as readable
API errors rather than blank panels.

## Verifying the console end to end

```sh
python scripts/console_journey.py      # ~2 min
python scripts/check_console_api.py    # route smoke tests, no browser
python scripts/check_console_ui.py     # form fill against a server already on :8000
```

`console_journey.py` is the real check. It starts an OpenAI-compatible stub
gateway plus the API and worker, seeds one public `memory_documents` row, then
drives Chromium through the flows a judge would care about:

1. ask a recall question and assert the answer arrives **with numbered citations**
2. submit a tier 0 request and watch it reach `completed` through the worker
3. submit a request whose plan contains a tier 2 tool, confirm it parks in
   `awaiting_approval` showing the tool name and arguments, approve it from the
   Approvals tab, and confirm the sidebar badge clears
4. check the Tasks table, screenshots into `snapshots/`, and fail on any page error

Because the stub answers the planner and the memory router, this proves the
transport and policy loop without spending inference credits. It does not prove
answer quality; for that, set a real key and use the console normally.

Note that `console_journey.py` binds port 8000 itself. Stop any other API first,
or the health probe succeeds against the wrong server and every model call goes
wherever that one points.

## Security posture

- Served only while `CUE_DEV_AUTH_UID` is set; `main.console_enabled()` returns
  404 otherwise, so a deployed container never exposes it.
- Same-origin fetches to `/v1/tenants/{tenant}/...`, so no CORS is configured and
  none is needed.
- The server injects the tenant id, caller uid, gateway URL, and a **boolean** for
  whether a gateway key exists. No secret value is ever sent to the browser.
- Row level security still applies: the console can only read what the `cue_app`
  role permits for that tenant, and memory answers are ACL-filtered per requester.

To ship a real frontend, keep the endpoint contract and drop the bypass: swap the
injected globals for a Firebase bearer token, and serve the assets from a static
host or CDN with the API origin allow-listed.
