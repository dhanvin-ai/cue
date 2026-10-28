-- Phase 6: one agent runtime for every channel. Tasks are the durable unit of work;
-- approvals gate non-autonomous actions; audit rows are append-only.
CREATE TABLE agent_tasks (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    id uuid NOT NULL,
    source text NOT NULL CHECK (source IN ('slack', 'email', 'web', 'schedule')),
    requester_uid text NOT NULL,
    channel_ref text,
    thread_ref text,
    request_text text NOT NULL,
    idempotency_key text NOT NULL,
    status text NOT NULL CHECK (status IN ('queued', 'running', 'awaiting_approval', 'completed', 'failed', 'cancelled')),
    plan jsonb,
    answer text,
    error text,
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    run_at timestamptz NOT NULL DEFAULT now(),
    dispatched_at timestamptz,
    recurrence text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, idempotency_key),
    FOREIGN KEY (tenant_id, requester_uid) REFERENCES users(tenant_id, firebase_uid)
);
CREATE INDEX agent_tasks_due_idx ON agent_tasks (tenant_id, run_at) WHERE status = 'queued';
CREATE INDEX agent_tasks_requester_idx ON agent_tasks (tenant_id, requester_uid, created_at DESC);

-- A tool call runs at most once per task attempt chain. Retries reuse the stored result.
CREATE TABLE agent_tool_runs (
    tenant_id uuid NOT NULL,
    task_id uuid NOT NULL,
    call_key text NOT NULL,
    tool text NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, task_id, call_key),
    FOREIGN KEY (tenant_id, task_id) REFERENCES agent_tasks(tenant_id, id) ON DELETE CASCADE
);

CREATE TABLE agent_approvals (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    task_id uuid NOT NULL,
    tool text NOT NULL,
    arguments jsonb NOT NULL,
    tier integer NOT NULL CHECK (tier BETWEEN 0 AND 4),
    status text NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
    decided_by text,
    decided_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, task_id, tool, arguments),
    FOREIGN KEY (tenant_id, task_id) REFERENCES agent_tasks(tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX agent_approvals_pending_idx ON agent_approvals (tenant_id, status, created_at);

CREATE TABLE agent_audit (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    id bigint GENERATED ALWAYS AS IDENTITY,
    task_id uuid,
    actor text NOT NULL,
    action text NOT NULL CHECK (action IN ('ingress', 'policy', 'tool', 'approval', 'response', 'retry')),
    tool text,
    tier integer,
    decision text,
    detail jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX agent_audit_task_idx ON agent_audit (tenant_id, task_id, created_at);

-- Tier defaults are code constants. Rows here only hold admin overrides.
CREATE TABLE agent_policies (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    scope text NOT NULL CHECK (scope IN ('tier', 'tool', 'person')),
    subject text NOT NULL,
    mode text NOT NULL CHECK (mode IN ('auto', 'approve', 'deny')),
    PRIMARY KEY (tenant_id, scope, subject)
);

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['agent_tasks', 'agent_tool_runs', 'agent_approvals',
                                      'agent_audit', 'agent_policies'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'CREATE POLICY tenant_access ON %I USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid)',
            table_name
        );
    END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE ON agent_tasks TO cue_app, cue_ingest;
GRANT SELECT, INSERT, UPDATE ON agent_tool_runs TO cue_app, cue_ingest;
GRANT SELECT, INSERT, UPDATE ON agent_approvals TO cue_app, cue_ingest;
GRANT SELECT, INSERT ON agent_audit TO cue_app, cue_ingest;
GRANT SELECT ON agent_policies TO cue_app, cue_ingest;
