# Connectors

Connectors bring each team tool into Cue's event pipeline and expose that tool's write actions to
the agent. Supported: GitHub, Gmail, Google Calendar, Calendly, Slack, Linear, and Recall.ai
meeting bots.

For step-by-step account setup, see [setup/SETUP.md](../../setup/SETUP.md).

## Contract

Every connector implements `cue/connectors/base.py`:

| Operation | Responsibility |
|---|---|
| `authorize(external_id)` | Verify that the credential belongs to the named mailbox, installation, workspace or organization before it is bound to a tenant. |
| `backfill(external_id, since)` | Page through vendor history from a saved cursor and yield raw records. The first run imports 365 days. |
| `subscribe()` | Register or verify push channels: Gmail watch, Calendar watch, webhooks. |
| `normalize(raw, tenant_id)` | Convert a vendor payload into a canonical event. |
| `acl(raw)` | Return the source principals allowed to see the event. |
| `tools()` | Declare write actions and their risk tiers. |

`cue/connectors/factory.py` builds a connector from a provider name, an external ID and a secret
reference.

## Credentials

Tokens never enter Postgres. `connector_connections.secret_ref` holds a reference only:

- **Production:** `projects/P/secrets/S/versions/latest` in Secret Manager.
- **Local:** `file:NAME/versions/latest`, which reads `.secrets/NAME` (gitignored).

OAuth secrets (Gmail, Calendar, Linear) are JSON with `access_token`, `refresh_token`,
`client_id`, `client_secret` and `expires_at` (Unix seconds). `cue/connectors/credentials.py`
refreshes expired tokens and writes a new secret version. Slack, Calendly and Recall secrets need
only `access_token`. The GitHub App mints short-lived installation tokens from its private key on
demand.

## Binding

Binding a source to a tenant is an operator action that needs the migration (admin) database
role. The API role cannot create bindings.

```sh
python scripts/connect_github.py TENANT INSTALLATION_ID
python scripts/bind_source.py TENANT gmail owner@example.com SECRET_REF [--no-subscribe]
python scripts/bind_source.py TENANT calendar owner@example.com SECRET_REF [--no-subscribe]
python scripts/bind_source.py TENANT calendly owner@example.com SECRET_REF
python scripts/bind_source.py TENANT slack WORKSPACE_ID SECRET_REF
python scripts/bind_source.py TENANT linear ORGANIZATION_ID SECRET_REF
```

Do not expose GitHub binding as a self-service endpoint: an installation ID in a setup redirect
can be spoofed. A self-service flow needs GitHub user authorization and a verified
account-to-tenant link.

## Keeping data fresh

| Source | Production | Local |
|---|---|---|
| GitHub | Signed webhooks to `/webhooks/github` (`X-Hub-Signature-256`) | Webhooks through a tunnel, plus polling |
| Gmail | Mailbox watch → `GMAIL_PUSH_TOPIC` → `process_gmail_notifications.py` | `poll_connectors.py` |
| Calendar | Watch channel → `/webhooks/calendar` → `SYNC_TRIGGERS_TOPIC` → `process_sync_triggers.py` | `poll_connectors.py` |
| Slack | Events API to `/webhooks/slack` (signing secret and timestamp checked) | Webhooks through a tunnel |
| Linear | Issue webhooks to `/webhooks/linear` (`Linear-Signature` checked) | Webhooks through a tunnel |
| Calendly | Polled (webhooks need a paid plan) | `poll_connectors.py` |
| Recall | `bot.done`, `transcript.done`, `transcript.data` to `/webhooks/recall` (workspace HMAC) | — |

Gmail and Calendar watches expire, so run `scripts/renew_watches.py` daily.
`scripts/backfill_connector.py TENANT CONNECTION` re-imports any single connection. Cursors
advance only after every raw publish succeeds, so a failed run retries from the same point.

## Access control

Source ACLs are deliberately conservative:

| Source | Who can see an event |
|---|---|
| GitHub | members of the repository |
| Gmail | the mailbox owner (and recipients when linked) |
| Calendar, Calendly | the owner and attendees or invitees |
| Slack | members of the channel |
| Linear | members of the team |
| Recall | the attendee list, or tenant admins when it is absent |

Holding an event ID is never permission to read it. The memory layer resolves the requester's
principals on every query.

## Agent tools

`cue/runtime/tools.py` builds the planner's tool catalog for each task from the tenant's bound
connections.

| Tool | Tier | Behaviour |
|---|---|---|
| `memory.query`, `calendly.list_event_types` | 0 | runs |
| `gmail.create_draft`, `slack.post_message`, `calendly.create_booking_link` | 1 | runs, logged |
| `github.create_issue`, `github.comment_issue`, `github.request_review`, `calendar.create_event`, `linear.create_issue` | 2 | one-click approval |
| `gmail.send` | 3 | explicit approval every time |

Gmail and Calendar writes act only as the agent's own account (`CUE_AGENT_EMAIL`). If several
mailboxes are bound and none matches, those tools are left out, so Cue never sends as a
teammate. `CUE_DEFAULT_REPO=owner/name` lets "file an issue" work without naming a repository.

## Known limits

- GitHub issues and pull requests backfill through GraphQL. Commits, comments and reviews use REST
  pagination.
- Webhook payloads above 9 MB are rejected because of Pub/Sub's 10 MB message limit.
  Reconciliation recovers the change. Storing oversized payloads directly in GCS is planned.
- A run that stops after publishing but before checkpointing republishes the same snapshot. The
  pipeline deduplicates by stable event ID.
- Not yet built: self-service OAuth consent, attachment downloads, Slack thread history, tracker
  comments, and Calendar channel cleanup.
