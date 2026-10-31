# Cue

**An AI teammate for software teams.** Cue has its own team identity: a mailbox, a calendar seat and
a GitHub App. It remembers what happens across your tools, answers questions in chat and out loud
in Google Meet, and carries out actions once a person approves them.

Built for the Bolna AI Buildathon.

---

## Highlights

- **Joins your meetings.** Cue enters Google Meet as a named participant. It listens, answers aloud
  when addressed ("Hey Cue, when are we shipping?"), and writes the summary, decisions and action
  items afterwards.
- **Team memory with citations.** GitHub, Gmail, Google Calendar, Calendly, Slack and Linear flow
  into one permission-aware memory. Every answer links back to its sources.
- **Respects access.** Answers are filtered by what the asker can already see in the source tool.
  Postgres row-level security keeps each team's data apart.
- **Acts, with approval.** Every action has a risk tier. Reads run on their own, drafts are
  logged, and issues, events and sent email wait for one-click approval.
- **Fast voice.** Streamed LLM replies, local Whisper speech-to-text and a Kokoro voice on the GPU.
  Cue starts speaking at the first finished sentence.
- **Web console.** Meetings, chat, memory, approvals and connected accounts in one place.

## Quick start

Requires Python 3.12+ and Docker.

| Windows | macOS / Linux |
|---|---|
| `setup\setup.bat` | `chmod +x setup/*.sh && ./setup/setup.sh` |
| `setup\start.bat` | `./setup/start.sh` |

Then open **http://localhost:8080/ui**.

To connect real accounts (Gemini key, Google Cloud OAuth for Gmail and Calendar, the GitHub App,
Calendly, Slack, Linear) and to send Cue into a meeting, follow **[setup/SETUP.md](setup/SETUP.md)**.

## How it works

```
Tools ──webhooks/polling──▶ event pipeline ──▶ memory (Postgres + Qdrant)
                                                     │
Google Meet ◀──voice── Attendee bot ──▶ Cue API ──▶ agent runtime ──▶ approved tool actions
                                          │
                                       console
```

1. **Connectors** sync each tool into canonical events and record who may see each one.
2. The **memory** layer builds documents, a temporal graph, vectors and rollup summaries.
3. The **agent runtime** builds context filtered by permissions, plans with an LLM (Gemini by
   default, through any OpenAI-compatible gateway), checks each tool call against the policy
   tiers, and records everything in an append-only audit log.
4. **Meetings** run through a self-hosted [Attendee](https://github.com/attendee-labs/attendee)
   bot. Cue speaks only when addressed.

The full walkthrough, code map and configuration reference are in
**[docs/GUIDE.md](docs/GUIDE.md)**.

## Repository layout

```
cue/          application package: API, connectors, memory, runtime, meetings, console
migrations/   numbered SQL migrations
scripts/      operator tools and background workers
setup/        setup and start scripts for Windows and macOS/Linux, plus SETUP.md
deploy/       speech-to-text and text-to-speech container configuration
docs/         guide, design notes (docs/design/) and operational notes
tests/        unit, integration and end-to-end API tests
```

## Tech stack

Python 3.12 · FastAPI · PostgreSQL 16 (row-level security) · Qdrant · Google Pub/Sub and Cloud
Storage (emulated locally) · Gemini through an OpenAI-compatible gateway · Attendee · Speaches
(Whisper, Kokoro) · Cloud Run

## Development

```sh
pytest -q              # unit and integration tests (needs db and qdrant running)
pytest -q tests/e2e    # end-to-end API journeys
```

CI runs both suites on every push (`.github/workflows/tests.yml`).

## Security

- Credentials live in Secret Manager in production and in the gitignored `.secrets/` folder
  locally. The database stores only references to them.
- `CUE_DEV_AUTH_UID` turns off sign-in for local development. Never set it on a server.
- To report a vulnerability, contact the maintainers privately rather than opening an issue.

## License

No license has been chosen yet. All rights are reserved until one is. See
[docs/licensing.md](docs/licensing.md).
