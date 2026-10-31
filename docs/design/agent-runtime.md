# Agent runtime

One runtime serves every interface: the console, Slack mentions, email to the agent's inbox,
meetings and schedules. Each request is normalized to a `RuntimeRequest` and saved as an
`agent_tasks` row before anything runs.

## Flow

```
ingress → context → planner → policy → executor → responder
```

- **Ingress.** `POST /v1/tenants/{t}/agent/requests`, `POST /webhooks/slack/agent` and
  `POST /webhooks/email/agent`. Slack and email requests are signature-verified.
- **Context.** Memory answers, already filtered by ACL. For Slack, access is intersected with the
  channel's members. Meetings add the recent conversation and the meeting's vocabulary.
- **Planner** (`cue/runtime/planner.py`). The model picks tools from the registry catalog. Unknown
  tools are dropped, and a plan with more than five calls is rejected. Meetings use
  `plan_streaming`: it uses native tool calling, so a plain answer is spoken while it streams. If
  streaming fails before any word was spoken, it falls back to the JSON planner.
- **Policy** (`cue/runtime/policy.py`):

  | Tier | Rule |
  |---|---|
  | 0, 1 | run automatically |
  | 2, 3 | need approval |
  | 4 | never runs |

  Admins may override tiers 0 to 2 per person, tool or tier. Tier 3 cannot be widened.
- **Approvals.** A task waits until the requester or a tenant admin decides, then resumes.
- **Retries.** Retries back off up to `max_attempts`. Each call is keyed by task, call index and
  arguments, so a retry reuses a finished result instead of repeating the side effect.
- **Scheduler.** `scripts/run_tasks.py`. `recurrence` takes a five-field cron expression. Tasks are
  queued with `CloudTasksQueue` in the cloud and `LocalQueue` locally.
- **Audit.** Every ingress, policy decision, tool run, approval, retry and response is appended to
  `agent_audit`.

## Model gateway

`cue/runtime/gateway.py` calls any OpenAI-compatible endpoint: Gemini, Straitly, OpenRouter or
LiteLLM.

- **Models.** `AGENT_PRIMARY_MODEL` is tried first, then `AGENT_FALLBACK_MODEL`. The fallback can sit
  on its own gateway (`MODEL_FALLBACK_GATEWAY_*`).
- **Reasoning.** Kept to a minimum on Gemini and turned off on OpenRouter, so a meeting reply isn't
  kept waiting.
- **Connections.** One pooled HTTP client is shared across calls.
- **Rate limits.** A 429 is retried once.
- **Streaming.** Only the primary model streams. A fallback answer after words were already spoken
  would talk over them.

## Adding a tool

1. Define `ToolSpec(name, tier, handler, description)`. Describe the arguments in the description
   as `Arguments: {"repo": "owner/name", "number": int}`. The streaming planner builds the JSON
   schema from that line.
2. `handler(arguments: dict)` must return JSON-serializable data and be safe to retry.
3. Register the tool in `cue/runtime/tools.py`.
4. Add a test for its approval behaviour if it is tier 2 or higher.

Cloud Tasks calls `/internal/tasks/{tenant}/{task}` with `X-Cue-Task-Token`.
