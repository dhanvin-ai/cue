# Real connectors on a local stack

Run GitHub, Gmail, Google Calendar, and Calendly against real accounts on one laptop, without a
GCP project. Vendor data is real. Only the GCP plumbing is replaced:

| Production | Local |
|---|---|
| Secret Manager | `.secrets/` files (gitignored), refs `file:NAME/versions/latest` |
| Pub/Sub | Pub/Sub emulator (`PUBSUB_EMULATOR_HOST`) |
| GCS raw bucket | fake-gcs-server (`STORAGE_EMULATOR_HOST`) |
| Gmail push, Calendar watch | `scripts/poll_connectors.py` every 60s |
| GitHub webhooks | ngrok to `/webhooks/github`, plus polling as a backstop |

## 1. Infrastructure

```sh
docker compose up -d db qdrant pubsub gcs
# uncomment the "Local stack" block in .env
python scripts/migrate.py && python scripts/ensure_partitions.py
python scripts/local_gcp.py          # topics, subscriptions, bucket
```

Run the workers in separate terminals: `scripts/process_raw.py`, `scripts/publish_outbox.py`,
`scripts/process_memory.py`, and `uvicorn cue.main:app`.

## 2. GitHub App

On the demo org: **Settings → Developer settings → GitHub Apps → New**.

- Webhook URL: `https://YOUR-NGROK/webhooks/github`. Generate a webhook secret.
- Repository permissions: Contents **read**, Issues **read & write**, Pull requests
  **read & write**, Metadata **read**.
- Events: Issues, Issue comment, Pull request, Pull request review,
  Pull request review comment, Push. Installation events are always sent.
- Create the app, generate a private key, and install it on the demo repo. The installation ID is
  in the URL of the installation settings page.

```sh
cp ~/Downloads/your-app.*.private-key.pem .secrets/github-app.pem
printf '%s' 'WEBHOOK_SECRET' > .secrets/github-webhook.txt
# .env: GITHUB_APP_ID=..., GITHUB_PRIVATE_KEY_SECRET_VERSION=file:github-app.pem/versions/latest
#       GITHUB_WEBHOOK_SECRET_VERSION=file:github-webhook.txt/versions/latest
python scripts/connect_github.py TENANT_UUID INSTALLATION_ID
```

## 3. Gmail and Google Calendar

In Google Cloud Console, enable the **Gmail API** and **Google Calendar API**. Configure the OAuth
consent screen and add the demo mailbox as a test user. Create an **OAuth client ID** of type
**Desktop app** and download the JSON.

```sh
python scripts/google_oauth.py ~/Downloads/client_secret_XXX.json cue@yourdomain.com
# then run the two printed bind_source.py commands (they include --no-subscribe)
```

The grant covers `gmail.modify` (read, draft, send, label) and `calendar` (read, create).
Send is still tier 3, so every external email needs explicit approval.

## 4. Calendly

**Integrations → API & Webhooks → Personal access tokens → Generate**.

```sh
printf '{"access_token": "%s"}' 'PAT' > .secrets/calendly.json
python scripts/bind_source.py TENANT_UUID calendly you@yourdomain.com \
    file:calendly/versions/latest
```

Scheduled events and their invitees enter memory with an ACL of the owner plus invitees. Tools:
`calendly.list_event_types` (tier 0) and `calendly.create_booking_link` (tier 1, single use).
Webhooks need a paid plan, so Calendly is polled.

## 5. Sync

```sh
python scripts/poll_connectors.py TENANT_UUID --once   # first import, 12 months
python scripts/poll_connectors.py TENANT_UUID          # keep fresh every 60s
```

## Agent tools

`cue/runtime/tools.py` builds the planner's catalog per task from the tenant's bound connections.
Tiers come from each connector's `tools()`:

| Tool | Tier | Default |
|---|---|---|
| `memory.query`, `calendly.list_event_types` | 0 | runs |
| `gmail.create_draft`, `calendly.create_booking_link`, `slack.post_message` | 1 | runs, logged |
| `github.create_issue`, `github.comment_issue`, `github.request_review`, `calendar.create_event`, `linear.create_issue` | 2 | one-click approval |
| `gmail.send` | 3 | explicit approval every time |

Gmail and Calendar writes act only as the agent's own account. Set `CUE_AGENT_EMAIL` to that
mailbox. With several mailboxes bound and none matching, those tools are left out, so Cue never
sends as a teammate. `CUE_DEFAULT_REPO=owner/name` lets "file an issue" work without naming a repo.

## Still open

- None of this has run against live accounts yet. Expect first-contact fixes in normalizers.
- Read tools such as `github.read_issue` have no handlers yet. Live reads go through
  `memory.query` and the query router.
