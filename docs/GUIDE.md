# Cue: end-to-end guide

Cue is an AI teammate for software teams. It has its own mailbox, calendar and GitHub identity. It
remembers what the team's tools say, answers questions in chat and out loud in Google Meet, and
carries out actions once a person approves them.

To get it running, see [setup/SETUP.md](../setup/SETUP.md). This document explains how the pieces fit.

## The system

```
 GitHub  Gmail  Calendar  Calendly  Slack  Linear                 Google Meet
    │      │       │         │        │      │                        │
    └──────┴── webhooks / polling ────┴──────┘                 Attendee bot (Docker)
                      │                                     audio ▲      │ transcript webhook
                      ▼                                           │      ▼
             raw Pub/Sub topic                             ┌──────────────────────┐
                      │  process_raw                       │   Cue API (FastAPI)  │
                      ▼                                    │  /webhooks/attendee  │
     GCS raw copy + canonical event log (Postgres, RLS)    │  /v1/.../agent       │
                      │  publish_outbox                    │  /ui  console        │
                      ▼                                    └──────────┬───────────┘
             canonical Pub/Sub topic                                  │
                      │  process_memory                               ▼
                      ▼                                     agent runtime
     documents · graph edges · vectors (Qdrant) · summaries ◀── context ─┤ planner (LLM)
                                                                         │ policy tiers
                                                                         │ executor ─▶ connector tools
                                                                         └ audit log
```

## Code map

| Path | Role |
|---|---|
| `cue/main.py` | FastAPI app: auth, every REST route, webhooks, `/ui` console |
| `cue/connectors/` | one module per vendor, plus `base.py` (contract), `factory.py`, `credentials.py` (OAuth refresh), `secret_store.py` (`file:` and Secret Manager refs), `backfill.py` |
| `cue/ingestion.py`, `cue/outbox.py` | raw-to-canonical worker logic and the transactional outbox |
| `cue/memory/` | projection into documents and the graph (`project.py`), vectors (`vector.py`), the query router (`query.py`), rollup summaries (`summary.py`) |
| `cue/runtime/` | agent turn: `ingress` → `context` → `planner` → `policy` → `executor` → `responder`, with `gateway` (LLM calls), `queue`, `scheduler`, `cron` |
| `cue/meetings/` | live meetings: `attendee.py` (bot and webhook), `addressing.py` (was Cue spoken to?), `speech.py` and `voice.py` (STT and TTS), `turns.py`, `notes.py` (post-meeting summary, decisions, actions) |
| `cue/proactive/` | digests, reminders, stale-PR nudges, quiet hours |
| `cue/controls/`, `cue/lifecycle/`, `cue/reconcile/`, `cue/audit/` | kill switches, deletion propagation, drift repair, audit export |
| `cue/static/` | the console (`console.html` / `console.js`) |
| `migrations/` | numbered SQL, applied by `scripts/migrate.py` |
| `scripts/` | operator and worker entry points (below) |
| `deploy/` | Kyutai STT image and the Kokoro-on-GPU patch for Speaches |

## Data model essentials

- **Tenancy.** Every tenant table has Postgres row-level security. The API connects as `cue_app`
  and sets `app.tenant_id` per transaction, so one team can never read another's rows even if a
  query has a bug.
- **Canonical events.** Each vendor payload becomes one event, with its source, actor, time,
  body, and an ACL of source principals. Events land in a monthly partitioned log.
  `ensure_partitions.py` creates the upcoming months.
- **Principals.** A member sees an event only if they hold one of its principals: a mailbox they
  own, a repo they belong to, or a channel they're in. `grant_principal.py` and
  `link_identity.py` connect a Cue member to their vendor identities.
- **Memory.** `process_memory` projects events into documents, temporal graph edges and Qdrant
  vectors. The query router answers counts, ownership, current status, recall and period
  questions from whichever store fits, and every answer cites the source events.

## One question, end to end

*"Hey Cue, when are we shipping?"* in a Meet call:

1. Attendee transcribes the speech with Whisper (or Meet captions) and posts it to
   `/webhooks/attendee/{tenant}` with the speaker's name.
2. `attendee.py` joins sentence fragments from the same speaker. It holds a piece 1.2 s and
   joins pieces less than 4 s apart. It drops lines speech models invent on silence ("thank
   you"), then stores the segment in the meeting transcript.
3. `addressing.py` decides whether Cue was spoken to. It accepts the name or a sound-alike as the
   first word, a direct "can you…/what do you…", or a follow-up within 45 s of Cue's last answer.
4. The runtime builds context. It takes the recent conversation plus memory hits, filtered by
   what the speaker may see.
5. `planner.plan_streaming` sends one streamed call to the model with native tool calling. A
   plain answer starts speaking at its first sentence. A tool call (for example `memory.query`
   or `github.create_issue`) goes through `policy.py`'s tiers: tier 0–1 run, and tier 2–3 wait
   in the console's **Activity** tab for approval.
6. The reply goes to TTS (Kokoro on the GPU, or Edge TTS) and plays into the call through
   Attendee's `output_audio`.
7. After the meeting, `notes.py` writes a summary, decisions and action items under the
   attendees' ACL, so they become memory for later questions.

Chat in the console follows the same steps from step 4 on, via `POST /v1/tenants/{t}/agent`.

## The console (`/ui`)

| Tab | Shows |
|---|---|
| Home | greeting, suggestion cards, quick ask |
| Meetings | upcoming calendar events, live transcript with Cue's answers and citations, past summaries |
| Chat | ask Cue anything; answers cite sources |
| Memory | browse and search what Cue knows |
| Activity | pending approvals and the audit trail |
| Settings | connected accounts, sync status, agent configuration, kill switches |

## Scripts reference

| Script | When |
|---|---|
| `setup/setup.bat` / `setup/setup.sh` | once per machine |
| `setup/start.bat` / `setup/start.sh` (`scripts/run_stack.py`) | every session |
| `migrate.py`, `ensure_partitions.py` | after pulling new migrations; monthly |
| `local_gcp.py` | creates emulator topics and the bucket |
| `seed_dev_tenant.py` | creates the demo tenant and admin |
| `google_oauth.py` | Gmail and Calendar consent for a mailbox |
| `connect_github.py` | binds a GitHub App installation |
| `bind_source.py` | binds Gmail, Calendar, Calendly, Slack, Linear or Recall |
| `poll_connectors.py [--once]` | local stand-in for push; first import with `--once` |
| `backfill_connector.py`, `replay_events.py` | re-import one connection; rebuild memory from the log |
| `build_summaries.py` | (re)build daily, weekly, monthly and yearly summaries |
| `join_meet.py` | sends Cue into a Meet |
| `renew_watches.py`, `process_gmail_notifications.py`, `process_sync_triggers.py`, `run_tasks.py` | production push and task workers |
| `check_console_api.py`, `check_console_ui.py`, `console_journey.py` | smoke tests against a running stack |

## Configuration

All settings are environment variables. `.env.example` lists every one with comments. The
groups that matter most:

| Group | Keys |
|---|---|
| Database | `MIGRATION_DATABASE_URL` (admin), `DATABASE_URL` (`cue_app`), `INGEST_DATABASE_URL` |
| Models | `MODEL_GATEWAY_BASE_URL`, `MODEL_GATEWAY_API_KEY_SECRET_VERSION`, `AGENT_PRIMARY_MODEL`, `AGENT_FALLBACK_MODEL`, `MEMORY_SMALL_MODEL`, optional `MODEL_FALLBACK_GATEWAY_*` |
| Pipeline | `RAW_EVENTS_*`, `CANONICAL_EVENTS_*`, `SYNC_TRIGGERS_*`, `RAW_GCS_BUCKET`, emulator hosts |
| Memory | `QDRANT_URL`, `EMBEDDING_BASE_URL`, `CUE_VECTOR_SEARCH=off` for keyword-only |
| Connectors | `GITHUB_*`, `CUE_AGENT_EMAIL`, `CUE_DEFAULT_REPO`, webhook secret refs |
| Meetings | `ATTENDEE_*`, `CUE_PUBLIC_URL`, `CUE_TRANSCRIBER`, `CUE_TTS`, `CUE_VOICE` |
| Dev only | `CUE_DEV_AUTH_UID`, `CUE_DEV_TENANT_ID` (bypass Firebase; never on a server) |

## Tests

```sh
pytest -q                 # unit and integration (needs db + qdrant up)
pytest -q tests/e2e       # API journeys over HTTP
```

See [testing.md](testing.md) for what each suite covers.

## Further reading

| Topic | Document |
|---|---|
| Connectors, credentials, ACLs and agent tools | [design/connectors.md](design/connectors.md) |
| Event pipeline and replay | [design/event-pipeline.md](design/event-pipeline.md) |
| Memory stores and query routing | [design/memory.md](design/memory.md) |
| Agent runtime, policy and model gateway | [design/agent-runtime.md](design/agent-runtime.md) |
| Meetings: Attendee, Bolna and Recall voice paths | [design/meetings.md](design/meetings.md) |
| Proactive work and admin controls | [design/operations.md](design/operations.md) |
| Web console | [console.md](console.md) |
| Tests | [testing.md](testing.md) |
| Licensing | [licensing.md](licensing.md) |
