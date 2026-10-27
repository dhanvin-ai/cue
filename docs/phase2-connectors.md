# Phase 2: connector framework

The code in `cue/connectors/base.py` defines the six connector operations in the architecture: `authorize`, `backfill`, `subscribe`, `normalize`, `acl`, and `tools`. GitHub is the first implementation. Its installation access token is generated when needed; neither that token nor the App private key is stored in Postgres.

## GitHub App setup

1. Register a GitHub App with **Issues: read** and **Pull requests: read** repository permissions. Enable the `installation`, `issues`, and `pull_request` webhook events. GitHub provides metadata read access to Apps.
2. Point the webhook URL at `POST /webhooks/github` on the Cue Cloud Run API. Set a random webhook secret in GitHub and store the same value in Google Secret Manager. Store the App private key in Secret Manager as a separate secret.
3. Set `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY_SECRET_VERSION`, `GITHUB_WEBHOOK_SECRET_VERSION`, and `RAW_EVENTS_TOPIC`. The last three values are resource names, not secret contents. Give the Cloud Run service account **Secret Manager Secret Accessor** on the two secrets and **Pub/Sub Publisher** on the raw-events topic.
4. Apply migrations with `python scripts/migrate.py`. This creates tenant-scoped connection records. The application role can read and update checkpoints, but only the migration/admin role can create a binding.
5. An operator with the migration/admin database credential verifies the intended tenant and GitHub account, then runs `python scripts/connect_github.py TENANT_UUID INSTALLATION_ID`. This manual binding is an administrative action. Do not expose this script as a user-facing endpoint: GitHub warns that an installation ID in a setup redirect can be spoofed. A self-service flow later needs GitHub user authorization and a verified account-to-tenant binding.
6. Run `python scripts/backfill_github.py TENANT_UUID CONNECTION_UUID`. The default first import covers the last 365 days. Subsequent runs use the saved timestamp cursor. It publishes raw snapshots to Pub/Sub and advances the cursor only after every publish is acknowledged. A failed run leaves the cursor in place for retry and marks the connection `error`.

The API and backfill job need `DATABASE_URL` for the restricted `cue_app` role. The migration and manual binding scripts need `MIGRATION_DATABASE_URL`; do not give that role to the API service. The Docker image includes the backfill script so it can run as a Cloud Run Job with a command override.

## Current boundary

- The webhook validates `X-Hub-Signature-256` before publishing. It includes the GitHub delivery ID and installation ID as Pub/Sub attributes. Phase 3 maps an installation to a tenant, stores the raw payload in GCS, deduplicates delivery IDs, and normalizes events.
- Payloads above 9 MB are rejected before Pub/Sub because of its 10 MB message limit. A future ingress change should store oversized raw payloads directly in GCS and publish a reference; reconciliation must recover missed changes meanwhile.
- Backfill covers GitHub issues and pull requests through the issues API. Commits, reviews, and comments belong to the deeper GitHub connector work in Phase 4.
- A retry may publish the same snapshot again if a run stops after publication but before checkpointing. Phase 3 deduplicates by stable event ID.
- OAuth token storage and refresh will be added with the Gmail, Calendar, Slack, and tracker connectors that require it. Their token values belong in Secret Manager, while `connector_connections.secret_ref` holds only the secret reference.
- Webhook event selection is configured on the GitHub App. `subscribe()` verifies that the required events are enabled; it does not change the App registration.
