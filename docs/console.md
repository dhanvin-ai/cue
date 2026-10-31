# Console

`GET /ui` serves Cue's web console. It is plain HTML, CSS and JavaScript in `cue/static/`, served
by the API itself. There is no build step and no CDN. The previous console stays available at
`/ui/classic`.

| Tab | What it does | Main endpoints |
|---|---|---|
| Home | Greeting, suggestion cards, quick ask | `POST /agent/requests` |
| Meetings | Upcoming calendar, live transcript with Cue's answers and citations, past summaries, join a call | `/meetings`, `/meetings/{id}/notes` |
| Chat | Ask Cue anything; answers cite sources | `/agent/requests`, `/agent/tasks/{id}` |
| Memory | Search what Cue knows | `POST /memory/query` |
| Activity | Pending approvals and the audit trail | `/agent/approvals`, `/admin/audit/export` |
| Settings | Connected accounts, sync status, agent configuration, kill switches | `/status`, `/admin/*` |

A banner reports whether a model gateway is configured and whether a worker is picking up tasks. A
task that stays `queued` past its dispatch deadline shows a **Requeue** button.

## Access

The console is a local and pilot surface. It is served only while `CUE_DEV_AUTH_UID` is set, and
returns 404 otherwise. That means:

- a deployed container never exposes it;
- fetches go to the same origin, so no CORS is needed;
- the page receives the tenant ID, the caller's UID, the gateway URL, and a *boolean* saying
  whether a key exists. It never receives a secret.

Row-level security and per-requester ACLs still apply to everything it shows.

To ship it publicly:

1. Replace the injected globals with a Firebase bearer token.
2. Serve the assets from a static host, with the API origin allow-listed.

## Checks

```sh
python scripts/console_journey.py     # full browser journey with a stub model (~2 min)
python scripts/check_console_api.py   # route smoke tests
python scripts/check_console_ui.py    # form checks against a running server
```

`console_journey.py` starts a stub OpenAI-compatible gateway, the API and a worker on port 8000,
so stop any other API on that port first. It then drives Chromium through these checks:

- a recall question returns an answer with citations;
- a tier 0 request completes;
- a tier 2 request waits for approval, is approved, and finishes;
- the tasks table renders.

It proves the transport and the policy loop, not the quality of the answers.
