# Phase 6: agent runtime and actions

One runtime serves every interface: Slack mentions, agent-inbox email, the web app, and schedules
normalize to a `RuntimeRequest` and persist an `agent_tasks` row before anything runs.

## Flow

`ingress -> context -> planner -> policy -> executor -> responder`; state and audit live in Postgres.

- Ingress: `POST /v1/tenants/{id}/agent/requests`, `POST /webhooks/slack/agent`,
  `POST /webhooks/email/agent`. Slack and email are signature-verified.
- Context: Phase 5 `query_memory`, already ACL-filtered. Slack intersects channel members.
- Planner: strict JSON tool calls from the registry catalog; unknown tools or >5 calls reject.
- Policy: PDF tiers. 0 and 1 auto-run; 2 and 3 need approval; 4 never runs. Admins may override
  tiers 0-2 per person, tool, or tier; tier 3 cannot be widened in v1.
- Approvals: block the task until the requester or a tenant admin decides, then resume it.
- Retries: backoff up to `max_attempts`; each call is keyed by task, index, and arguments so a retry
  reuses a completed result instead of repeating the side effect.
- Scheduler: `scripts/run_tasks.py`; `recurrence` is five-field cron; `CloudTasksQueue` in cloud, `LocalQueue` locally.
- Gateway: LiteLLM with `AGENT_PRIMARY_MODEL`, falling back to `AGENT_FALLBACK_MODEL`.

Every ingress, policy decision, tool run, approval, retry, and response is appended to `agent_audit`.

## Setup

Apply `006_agent_runtime.sql`, set the model and secret variables plus `CLOUD_TASKS_*`, then:

```sh
python scripts/run_tasks.py --tenant TENANT_UUID
```

Cloud Tasks calls `/internal/tasks/{tenant_id}/{task_id}` with `X-Cue-Task-Token`. That worker starts
with an empty registry, so register handlers before enabling writes.

## Adding a tool

1. Create `ToolSpec(name, tier, handler, description)` and register it in the worker's `ToolRegistry`.
2. `handler(arguments: dict)` returns JSON-serializable data and must be safe to retry.
3. Cover tier 2+ approval behaviour with a test.
