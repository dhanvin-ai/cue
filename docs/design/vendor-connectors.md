# Vendor connectors

This phase follows the PDF's six groups: Gmail, Google Calendar, Google Meet/Zoom through a meeting-bot API, Slack, GitHub, and one tracker. We selected **Linear** for the tracker and **Recall.ai** for the meeting-bot adapter. The code paths reach the Phase 3 raw Pub/Sub topic and retain ACLs in canonical events. Live vendor credentials and GCP resources are required to exercise them outside mocks.

## Provisioning and credentials

Apply migration 004, then run `scripts/ensure_partitions.py`. Keep each vendor token as a JSON secret in Secret Manager, and store only its `/versions/latest` resource name in `connector_connections.secret_ref`. For Gmail, Calendar and Linear OAuth tokens, the JSON needs `access_token`, `refresh_token`, `client_id`, `client_secret`, and numeric `expires_at` (Unix seconds). The credential helper refreshes expired tokens and adds a new secret version. Slack and Recall secrets need `access_token`. An operator must obtain initial OAuth grants with the required scopes and create these secrets; self-service authorization and consent screens are not yet implemented.

Bind a verified account with:

```sh
python scripts/bind_source.py TENANT_UUID gmail owner@example.com projects/PROJECT/secrets/cue-gmail-owner/versions/latest
python scripts/bind_source.py TENANT_UUID calendar owner@example.com projects/PROJECT/secrets/cue-calendar-owner/versions/latest
python scripts/bind_source.py TENANT_UUID slack WORKSPACE_ID projects/PROJECT/secrets/cue-slack-workspace/versions/latest
python scripts/bind_source.py TENANT_UUID linear ORGANIZATION_ID projects/PROJECT/secrets/cue-linear-org/versions/latest
```

The script verifies the vendor identity before writing the tenant binding. The binding may be created only with the migration/admin database role. `python scripts/backfill_connector.py TENANT_UUID CONNECTION_UUID` runs any bound connector; use it after binding and for six-hour reconciliation. A default first run imports one year of changes. Per-source cursors advance only when every raw publish succeeds.

For meetings, create a bot with a visible AI name and an attendee ACL before its scheduled join:

```sh
python scripts/create_meeting_bot.py TENANT_UUID projects/PROJECT/secrets/cue-recall/versions/latest https://meet.google.com/abc-defg-hij --attendee person@example.com
```

The script binds the returned bot ID to the tenant. Recall status and real-time transcript webhooks enter the raw topic. A `transcript.done` webhook triggers retrieval of the normalized transcript and publishes each segment for ingestion. Meeting voice and turn-taking remain Phase 7.

## Live subscriptions

- **GitHub:** enable installation, issues, pull_request, push, issue_comment, pull_request_review and pull_request_review_comment events. Read scopes: Issues, Pull requests, Contents. Write actions need the matching write scopes. The webhook verifies `X-Hub-Signature-256`.
- **Slack:** configure Events API message events for channels and DMs the app can access; set `/webhooks/slack` as the Request URL. Grant `channels:history`, `groups:history`, `im:history`, `mpim:history`, `channels:read`, `groups:read`, `im:read`, `mpim:read`, and `chat:write` for enabled actions. Cue checks Slack's signing secret and timestamp.
- **Linear:** configure Issue webhooks to `/webhooks/linear`, with read and optional write OAuth scopes. Cue checks `Linear-Signature` and the delivery timestamp. Configure the signing secret in Secret Manager.
- **Gmail:** grant `gmail.readonly` for sync and `gmail.compose`/`gmail.send` only when those actions are enabled. The mailbox watch publishes to `GMAIL_PUSH_TOPIC`. Grant `gmail-api-push@system.gserviceaccount.com` publisher access, then run `scripts/process_gmail_notifications.py` on `GMAIL_PUSH_SUBSCRIPTION`. Run `scripts/renew_watches.py` daily because Gmail watches expire.
- **Calendar:** grant `calendar.events.readonly` for sync and `calendar.events` for creating events. The watch callback is `/webhooks/calendar`; Cue authenticates the signed channel token and puts a sync trigger on `SYNC_TRIGGERS_TOPIC`. Run `scripts/renew_watches.py` daily.
- **Recall:** configure workspace verification and webhook events including `bot.done`, `transcript.done`, and real-time `transcript.data` to `/webhooks/recall`. The callback verifies the workspace HMAC. Use the matching `RECALL_REGION` and Secret Manager verification secret.

Run `scripts/process_sync_triggers.py` on `SYNC_TRIGGERS_SUBSCRIPTION`. It resolves the source binding before starting a tenant-scoped sync. Configure dead-letter topics on raw, Gmail push, and sync-trigger subscriptions. Restrict publisher/subscriber IAM to each service. The API, backfill, raw worker, and sync workers have distinct credentials; no vendor token enters Postgres.

The connector methods advertise risk tiers but are **not exposed as user actions** until Phase 6 adds authenticated requester context and approval checks. Source ACLs are conservative: Gmail owner, Calendar owner and attendees, Slack channel, Linear team, and Recall attendee list (or admins when absent). Phase 5 must resolve these principals before retrieval; possession of an event ID is not permission to read it.

## Current limits

These adapters are tested with mock vendor APIs and Postgres integration tests. No live vendor account, OAuth grant, GCP project, or Recall workspace was available for end-to-end verification. Initial OAuth consent, automated connector revocation, attachment downloads, Slack thread history, tracker comments, and calendar channel cleanup remain production work. The six-hour reconciliation scheduler must be configured in GCP. GitHub issues and pull requests backfill through GraphQL; commits, comments, and reviews use REST pagination. Oversized webhooks still need the direct-to-GCS ingress path noted in Phase 3.
