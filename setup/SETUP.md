# Setup: running Cue and connecting your tools

This guide takes a fresh machine to a running Cue that reads your real GitHub, Gmail, Calendar and
Calendly and joins Google Meet. For how the system works inside, see
[docs/GUIDE.md](../docs/GUIDE.md).

- [1. Prerequisites](#1-prerequisites)
- [2. Install and first run](#2-install-and-first-run)
- [3. How connectors work](#3-how-connectors-work)
- [4. Model API key (Gemini)](#4-model-api-key-gemini)
- [5. Google Cloud: Gmail and Calendar](#5-google-cloud-gmail-and-calendar)
- [6. GitHub App](#6-github-app)
- [7. Calendly, Slack and Linear](#7-calendly-slack-and-linear)
- [8. Meeting bot: Attendee, voice and the tunnel](#8-meeting-bot-attendee-voice-and-the-tunnel)
- [9. Deploying on real GCP](#9-deploying-on-real-gcp)
- [10. Troubleshooting](#10-troubleshooting)

## 1. Prerequisites

| Tool | Why | Get it |
|---|---|---|
| Python 3.12+ | API and workers | python.org, or `brew install python@3.12` |
| Docker Desktop | Postgres, Qdrant, Pub/Sub and GCS emulators, Attendee | docker.com |
| Git | clone Cue and Attendee | git-scm.com |
| cloudflared | public HTTPS URL for webhooks (optional) | `winget install Cloudflare.cloudflared` / `brew install cloudflared` |
| NVIDIA GPU + driver | local Whisper speech-to-text and Kokoro voice (optional) | Without one, Cue falls back to Meet captions and Edge TTS |

You also need a Google account to act as Cue's own mailbox (for example
`cue.teammate@gmail.com`) and admin access to a GitHub org or repo.

## 2. Install and first run

```sh
git clone https://github.com/dhanvin-ai/cue && cd cue
```

| Windows | macOS / Linux |
|---|---|
| `setup\setup.bat` | `chmod +x setup/*.sh && ./setup/setup.sh` |
| `setup\start.bat` | `./setup/start.sh` |

`setup` is a one-time step and safe to rerun. It:

1. creates `.venv` and installs Cue,
2. copies `.env.example` to `.env` and creates `.secrets/`,
3. starts Postgres (port 5433), Qdrant, and the Pub/Sub and GCS emulators in Docker,
4. runs the migrations, which also create the restricted `cue_app` and `cue_ingest` roles,
5. creates the local topics, subscriptions and raw bucket,
6. adds the demo tenant `11111111-1111-1111-1111-111111111111` with admin `dev-local-user`.

Before the first `start`, open `.env` and:

- uncomment the **Local stack** block (emulators and `file:` secrets),
- set `CUE_DEV_AUTH_UID=dev-local-user` and `CUE_DEV_TENANT_ID=11111111-1111-1111-1111-111111111111`. This turns on the console without Firebase. Never set these on a server.
- set `CUE_VECTOR_SEARCH=off`, unless you run an embedding server at `EMBEDDING_BASE_URL`,
- add a model key (section 4).

`start` brings up Docker, then runs the API and every worker in one window, each line tagged with
its process name. Ctrl+C stops them all. Open **http://localhost:8080/ui** for the console.

| Flag | Effect |
|---|---|
| `--voice` | also starts the GPU Whisper and Kokoro container (`docker compose --profile stt up -d whisper`) |
| `--tunnel` | also opens a Cloudflare quick tunnel to port 8080 |

To run the pieces by hand, `scripts/run_stack.py` starts `uvicorn cue.main:app`,
`scripts/process_raw.py`, `scripts/publish_outbox.py`, `scripts/process_memory.py` and
`scripts/poll_connectors.py TENANT`.

> **Postgres outside Docker.** If you already run Postgres natively, point `MIGRATION_DATABASE_URL`,
> `DATABASE_URL` and `INGEST_DATABASE_URL` at it, then skip `db` in `docker compose up`.

## 3. How connectors work

Every connector follows one contract (`cue/connectors/base.py`):

| Step | What it does |
|---|---|
| `authorize(external_id)` | proves the credential really belongs to that mailbox, org or workspace before Cue binds it |
| `backfill(external_id, since)` | pages through vendor history from a cursor; the first run imports 12 months |
| `subscribe()` | registers push channels (webhooks, Gmail watch); skipped locally with `--no-subscribe` |
| `normalize(raw)` | turns a vendor payload into one canonical event |
| `acl(raw)` | records who may see it: the mailbox owner and recipients, repo members, channel members |
| `tools()` | the write actions the agent may call, each with a risk tier |

Data moves through one pipeline:

```
vendor ──webhook / poll──▶ raw Pub/Sub topic ──process_raw──▶ GCS raw copy
                                                          └─▶ canonical event log (Postgres)
outbox ──publish_outbox──▶ canonical topic ──process_memory──▶ documents, graph, vectors, summaries
```

**Credentials.** A connection row stores only a secret reference, never the token. Locally the
reference is `file:NAME/versions/latest`, which reads `.secrets/NAME` (or `NAME.json`). In
production it is a Secret Manager path, `projects/P/secrets/S/versions/latest`. OAuth tokens
refresh themselves and write the new version back.

**Freshness.** In production, Gmail pushes through Pub/Sub, Calendar through watch channels, and
GitHub, Slack and Linear through signed webhooks. Locally, `poll_connectors.py` re-runs each
connector's backfill every 60 s. Cursors keep it incremental.

**Permissions.** Every answer is filtered by the requester's source principals. Cue never tells
you something from a mailbox or repo you can't see. Agent actions are tiered:

| Tier | Example tools | Behaviour |
|---|---|---|
| 0 | `memory.query`, `calendly.list_event_types` | runs |
| 1 | `gmail.create_draft`, `slack.post_message`, `calendly.create_booking_link` | runs, logged |
| 2 | `github.create_issue`, `github.comment_issue`, `calendar.create_event`, `linear.create_issue` | one-click approval in Activity |
| 3 | `gmail.send` | explicit approval every time |

## 4. Model API key (Gemini)

Cue calls any OpenAI-compatible endpoint. The default is Gemini through Google's compatible API.

1. Go to **https://aistudio.google.com/apikey → Create API key**. Pick or create a GCP project.
2. Save the key and point `.env` at it:

```sh
printf '%s' 'YOUR_GEMINI_KEY' > .secrets/gemini.txt
```

```ini
MODEL_GATEWAY_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
MODEL_GATEWAY_API_KEY_SECRET_VERSION=file:gemini.txt/versions/latest
AGENT_PRIMARY_MODEL=gemini-3.5-flash-lite
AGENT_FALLBACK_MODEL=gemini-2.5-flash
MEMORY_SMALL_MODEL=gemini-3.5-flash-lite
```

On Windows, create the file with `Set-Content -NoNewline .secrets\gemini.txt 'KEY'` or a text
editor. Make sure the file has no trailing newline.

**Other providers.** Set `MODEL_GATEWAY_BASE_URL` to Straitly (`https://api.straitly.ai`),
OpenRouter (`https://openrouter.ai/api`), or a LiteLLM proxy, and use that provider's model names.
To put the fallback model on a different provider, set `MODEL_FALLBACK_GATEWAY_BASE_URL` and
`MODEL_FALLBACK_GATEWAY_API_KEY_SECRET_VERSION`.

## 5. Google Cloud: Gmail and Calendar

Both connectors share one OAuth grant on Cue's own mailbox.

1. **Create or choose a project.** Open https://console.cloud.google.com and use the project picker, then **New project** (for example `cue-demo`).
2. **Enable the APIs.** Go to **APIs & Services → Library** and enable **Gmail API** and **Google Calendar API**.
3. **Set up the consent screen.** Go to **APIs & Services → OAuth consent screen** (or **Google Auth Platform → Branding**).
   - User type: **External**. App name: `Cue`. Add your support email.
   - Scopes: `.../auth/gmail.modify` and `.../auth/calendar`.
   - **Audience → Test users**: add Cue's mailbox. While the app is in *Testing*, only test users can grant access, and refresh tokens expire after 7 days. Re-run step 5 when that happens, or publish the app.
4. **Create the client.** Go to **Credentials → Create credentials → OAuth client ID**, type **Desktop app**, and download the JSON.
5. **Grant access.** Run this; a browser opens, and you sign in as Cue's mailbox:

   ```sh
   python scripts/google_oauth.py path/to/client_secret_XXX.json cue.teammate@gmail.com
   ```

   It stores the grant in `.secrets/google-<mailbox>.json` and prints two commands. Run them:

   ```sh
   python scripts/bind_source.py 11111111-1111-1111-1111-111111111111 gmail cue.teammate@gmail.com file:google-cue-teammate-gmail-com/versions/latest --no-subscribe
   python scripts/bind_source.py 11111111-1111-1111-1111-111111111111 calendar cue.teammate@gmail.com file:google-cue-teammate-gmail-com/versions/latest --no-subscribe
   ```

6. **Set Cue's own identity.** Set `CUE_AGENT_EMAIL=cue.teammate@gmail.com` in `.env`. Gmail and Calendar *writes* only ever act as this account.

**Production push (optional).** Create a Pub/Sub topic `cue-gmail-push` and grant
`gmail-api-push@system.gserviceaccount.com` the **Pub/Sub Publisher** role on it. Set
`GMAIL_PUSH_TOPIC` and `GMAIL_PUSH_SUBSCRIPTION`, then bind without `--no-subscribe`. Calendar
watch needs a public HTTPS `CALENDAR_WEBHOOK_URL` (`/webhooks/calendar`) and a channel secret.
Run `scripts/renew_watches.py` daily, because watches expire.

## 6. GitHub App

1. Open **GitHub → your org (or account) → Settings → Developer settings → GitHub Apps → New GitHub App**.
2. Fill in the app:
   - Name: `cue-yourteam`. Homepage: any URL.
   - Webhook URL: `https://YOUR-TUNNEL/webhooks/github` (section 8). Click **Generate** next to the webhook secret and copy it.
   - Repository permissions: Contents **Read**, Metadata **Read**, Issues **Read & write**, Pull requests **Read & write**.
   - Subscribe to events: Issues, Issue comment, Pull request, Pull request review, Pull request review comment, Push.
3. **Create**. Note the **App ID**, then **Generate a private key**, which downloads a `.pem` file.
4. **Install App** on the demo repo. The installation ID is the number at the end of the installation's settings URL.
5. Wire it up:

   ```sh
   cp ~/Downloads/cue-yourteam.*.private-key.pem .secrets/github-app.pem
   printf '%s' 'WEBHOOK_SECRET' > .secrets/github-webhook.txt
   ```

   ```ini
   GITHUB_APP_ID=123456
   GITHUB_PRIVATE_KEY_SECRET_VERSION=file:github-app.pem/versions/latest
   GITHUB_WEBHOOK_SECRET_VERSION=file:github-webhook.txt/versions/latest
   CUE_DEFAULT_REPO=your-org/your-repo
   ```

   ```sh
   python scripts/connect_github.py 11111111-1111-1111-1111-111111111111 INSTALLATION_ID
   ```

Webhooks give near-instant updates. Polling still catches anything a webhook misses while your
laptop is offline.

## 7. Calendly, Slack and Linear

**Calendly.** Go to **Integrations → API & Webhooks → Personal access tokens → Generate**.

```sh
printf '{"access_token": "%s"}' 'PAT' > .secrets/calendly.json
python scripts/bind_source.py TENANT calendly you@yourdomain.com file:calendly/versions/latest --no-subscribe
```

Calendly webhooks need a paid plan, so it is polled.

**Slack.**

1. Create an app at https://api.slack.com/apps.
2. Bot scopes: `channels:history`, `channels:read`, `chat:write`, `users:read`.
3. Event subscription URL: `https://YOUR-TUNNEL/webhooks/slack`.
4. Install it to the workspace, then save the bot token and signing secret:

```sh
printf '{"access_token": "%s"}' 'xoxb-...' > .secrets/slack.json
printf '%s' 'SIGNING_SECRET' > .secrets/slack-signing.txt
# .env: SLACK_SIGNING_SECRET_VERSION=file:slack-signing.txt/versions/latest
python scripts/bind_source.py TENANT slack WORKSPACE_ID file:slack/versions/latest
```

**Linear.**

1. Go to **Settings → API → Personal API keys** (or create an OAuth app).
2. Add a webhook to `https://YOUR-TUNNEL/webhooks/linear` and copy its signing secret.
3. Save the key and bind it:

```sh
printf '{"access_token": "%s"}' 'lin_api_...' > .secrets/linear.json
# .env: LINEAR_WEBHOOK_SECRET_VERSION=file:linear-webhook.txt/versions/latest
python scripts/bind_source.py TENANT linear ORGANIZATION_ID file:linear/versions/latest
```

After binding anything, run a first import, then let `start` keep it fresh:

```sh
python scripts/poll_connectors.py 11111111-1111-1111-1111-111111111111 --once
```

The console's **Settings** tab lists each connection and when it last synced.

## 8. Meeting bot: Attendee, voice and the tunnel

Cue joins Google Meet as a named participant through self-hosted
[Attendee](https://github.com/attendee-labs/attendee) (Elastic 2.0, free to self-host).

1. **Run Attendee next to Cue:**

   ```sh
   git clone https://github.com/attendee-labs/attendee ../attendee && cd ../attendee
   docker compose -f dev.docker-compose.yaml build
   docker compose -f dev.docker-compose.yaml run --rm attendee-app-local python init_env.py > .env
   docker compose -f dev.docker-compose.yaml up -d
   docker compose -f dev.docker-compose.yaml exec attendee-app-local python manage.py migrate
   ```

   Then set up Attendee itself:

   - Open http://localhost:8000 and sign up. The confirmation link is in the server log.
   - Create an **API key** and a **webhook secret**.
   - If Cue and Attendee run on the same machine, set `REQUIRE_HTTPS_WEBHOOKS=false` in Attendee's `.env`.

2. **Point Cue at it:**

   ```sh
   printf '%s' 'ATTENDEE_API_KEY' > .secrets/attendee-api-key.txt
   printf '%s' 'ATTENDEE_WEBHOOK_SECRET' > .secrets/attendee-webhook.txt
   ```

   ```ini
   ATTENDEE_URL=http://localhost:8000
   ATTENDEE_API_KEY_SECRET_VERSION=file:attendee-api-key.txt/versions/latest
   ATTENDEE_WEBHOOK_SECRET_VERSION=file:attendee-webhook.txt/versions/latest
   # Same machine: Attendee's containers reach Cue directly, no tunnel needed.
   ATTENDEE_WEBHOOK_BASE_URL=http://host.docker.internal:8080
   ```

3. **Voice (optional, NVIDIA GPU).** Run `start --voice` (`setup\start.bat --voice` or `./setup/start.sh --voice`), then set:

   ```ini
   CUE_TRANSCRIBER=whisper   # whisper | kyutai | captions
   CUE_TTS=kokoro
   CUE_VOICE=af_heart
   ```

   Without a GPU, use `CUE_TRANSCRIBER=captions`. Cue then speaks with Edge TTS, which needs no key.

4. **Public URL (needed for GitHub, Slack and Linear webhooks, or a remote Attendee):**

   ```sh
   cloudflared tunnel --url http://localhost:8080
   ```

   Put the printed `https://….trycloudflare.com` URL in `CUE_PUBLIC_URL` and in each vendor's webhook settings. A quick tunnel's URL **changes every run**, so update those settings each time, or create a named Cloudflare tunnel for a fixed hostname.

5. **Join a meeting:**

   ```sh
   python scripts/join_meet.py 11111111-1111-1111-1111-111111111111 https://meet.google.com/abc-defg-hij --attendee you@yourdomain.com
   ```

   You can also use **Meetings → Join** in the console. Admit "Cue" in Meet, then talk to it: *"Hey Cue, what shipped this week?"* Cue answers when:

   - you say its name, or a sound-alike such as "Q",
   - you ask it directly ("can you…", "what do you think…"),
   - or you ask a follow-up within 45 s of its last answer.

## 9. Deploying on real GCP

The local stack swaps GCP services for stand-ins one-for-one, so production means replacing them
back:

| Local | GCP |
|---|---|
| Postgres in Docker | Cloud SQL for PostgreSQL 16; run `migrate.py` with the admin role, and run the API as `cue_app` |
| `.secrets/` + `file:` refs | Secret Manager + `projects/P/secrets/S/versions/latest` refs; grant the service account **Secret Manager Secret Accessor** |
| Pub/Sub emulator | Pub/Sub topics `cue-raw-events`, `cue-canonical-events`, `cue-sync-triggers`, `cue-gmail-push`, each with a pull subscription |
| fake-gcs-server | a GCS bucket for raw payloads (`RAW_GCS_BUCKET`) |
| `poll_connectors.py` | Gmail push, Calendar watch and webhooks, plus a Cloud Scheduler job for `renew_watches.py` and reconciliation |
| `uvicorn` in a terminal | Cloud Run from the repo `Dockerfile` |
| workers in a terminal | Cloud Run jobs or services running each `scripts/process_*.py` |
| dev auth bypass | Firebase Auth: set `FIREBASE_PROJECT_ID`, and unset `CUE_DEV_*` |
| Cloud Tasks | queue `cue-agent-tasks` in `CLOUD_TASKS_LOCATION`, targeting the API (`CLOUD_TASKS_*`) |

Minimal commands:

```sh
gcloud services enable run.googleapis.com sqladmin.googleapis.com pubsub.googleapis.com \
  secretmanager.googleapis.com cloudtasks.googleapis.com gmail.googleapis.com calendar-json.googleapis.com
for t in cue-raw-events cue-canonical-events cue-sync-triggers cue-gmail-push; do
  gcloud pubsub topics create $t && gcloud pubsub subscriptions create $t-worker --topic $t; done
gcloud storage buckets create gs://YOUR-cue-raw --location=asia-south1
printf '%s' 'KEY' | gcloud secrets create model-gateway-key --data-file=-
gcloud run deploy cue-api --source . --region asia-south1 --set-env-vars-file env.prod.yaml
```

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `connection refused` on 5433 | Docker is not running, or Postgres is still starting. Run `docker compose ps`. |
| `Tenant not found` | Run `python scripts/seed_dev_tenant.py`. |
| `/ui` returns 404 | Set `CUE_DEV_AUTH_UID` and `CUE_DEV_TENANT_ID` in `.env`. |
| Google `invalid_grant` | The test-mode refresh token expired (7 days). Re-run `google_oauth.py`. |
| GitHub webhook 401 | The webhook secret in GitHub differs from `.secrets/github-webhook.txt`. |
| Cue joins but never speaks | Check that the webhook URL reaches `/webhooks/attendee/TENANT`, and that you addressed Cue by name. |
| Cue's answers come slowly | Cold Whisper or TTS. Keep the `--voice` container running; first answers warm it up. |
| Workers stop at random | Low memory. Close heavy apps, or run without `--voice`. |
| `ModelUnavailable` | Wrong key or model name, or a rate limit. Check `MODEL_GATEWAY_*`. |

**Security.** `.env` and `.secrets/` are gitignored; keep it that way. Rotate any key you have
pasted into a chat, a screen share or a recording.
