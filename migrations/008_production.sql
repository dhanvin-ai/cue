-- Phase 8: proactive rules, quiet hours, controls, deletion, reconciliation, and audit export.
CREATE TABLE proactive_rules (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    id uuid NOT NULL,
    rule_key text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('daily_digest', 'weekly_digest', 'reminder',
                                       'stale_pr', 'overdue_action')),
    schedule text,
    timezone text NOT NULL DEFAULT 'UTC',
    owner_uid text NOT NULL,
    config jsonb NOT NULL DEFAULT '{}',
    enabled boolean NOT NULL DEFAULT true,
    next_run_at timestamptz,
    last_run_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, rule_key),
    FOREIGN KEY (tenant_id, owner_uid) REFERENCES users(tenant_id, firebase_uid)
);
CREATE INDEX proactive_rules_due_idx ON proactive_rules (tenant_id, enabled, next_run_at);

CREATE TABLE proactive_mutes (
    tenant_id uuid NOT NULL,
    firebase_uid text NOT NULL,
    rule_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, firebase_uid, rule_key),
    FOREIGN KEY (tenant_id, firebase_uid) REFERENCES users(tenant_id, firebase_uid)
);

CREATE TABLE proactive_runs (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    rule_id uuid NOT NULL,
    run_key text NOT NULL,
    status text NOT NULL CHECK (status IN ('queued', 'deferred', 'dispatched', 'skipped', 'failed')),
    deliver_after timestamptz,
    task_id uuid,
    payload jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, rule_id, run_key),
    FOREIGN KEY (tenant_id, rule_id) REFERENCES proactive_rules(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, task_id) REFERENCES agent_tasks(tenant_id, id)
);
CREATE INDEX proactive_runs_release_idx ON proactive_runs (tenant_id, status, deliver_after);

-- A user row overrides the tenant row. Windows may cross midnight.
CREATE TABLE quiet_hours (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    scope text NOT NULL CHECK (scope IN ('tenant', 'user')),
    subject text NOT NULL DEFAULT '*',
    timezone text NOT NULL,
    start_time time NOT NULL,
    end_time time NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, scope, subject)
);

-- Paused connectors either queue raw deliveries or drop them.
CREATE TABLE kill_switches (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    scope text NOT NULL CHECK (scope IN ('tenant', 'connector')),
    subject text NOT NULL DEFAULT '*',
    paused boolean NOT NULL DEFAULT true,
    mode text NOT NULL DEFAULT 'queue' CHECK (mode IN ('queue', 'drop')),
    reason text,
    changed_by text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, scope, subject)
);

CREATE TABLE paused_events (
    tenant_id uuid NOT NULL,
    id bigint GENERATED ALWAYS AS IDENTITY,
    source text NOT NULL,
    delivery_id text,
    attributes jsonb NOT NULL,
    payload bytea NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    replayed_at timestamptz,
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX paused_events_pending_idx ON paused_events (tenant_id, id) WHERE replayed_at IS NULL;

-- Tombstones stop re-projection and deletion is retried until every store is clean.
CREATE TABLE deletion_tombstones (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    id uuid NOT NULL,
    event_id text,
    source text,
    reason text NOT NULL,
    requested_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX deletion_tombstones_event_idx ON deletion_tombstones (tenant_id, event_id);

CREATE TABLE access_revocations (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('user', 'connector')),
    subject text NOT NULL,
    reason text NOT NULL,
    revoked_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE reconciliation_runs (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    connection_id uuid NOT NULL,
    provider text NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    provider_count integer NOT NULL DEFAULT 0,
    event_count integer NOT NULL DEFAULT 0,
    missing_count integer NOT NULL DEFAULT 0,
    backfilled_count integer NOT NULL DEFAULT 0,
    drift jsonb NOT NULL DEFAULT '{}',
    error text,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (connection_id) REFERENCES connector_connections(id)
);
CREATE INDEX reconciliation_runs_recent_idx
    ON reconciliation_runs (tenant_id, provider, finished_at DESC);

ALTER TABLE users ADD COLUMN revoked_at timestamptz;
ALTER TABLE connector_connections DROP CONSTRAINT connector_connections_status_check;
ALTER TABLE connector_connections ADD CONSTRAINT connector_connections_status_check
    CHECK (status IN ('active', 'error', 'disabled', 'revoked'));

ALTER TABLE agent_audit DROP CONSTRAINT agent_audit_action_check;
ALTER TABLE agent_audit ADD CONSTRAINT agent_audit_action_check
    CHECK (action IN ('ingress', 'policy', 'tool', 'approval', 'response', 'retry',
                      'control', 'deletion', 'revocation', 'export', 'reconciliation', 'proactive'));

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['proactive_rules', 'proactive_mutes', 'proactive_runs',
                                      'quiet_hours', 'kill_switches', 'paused_events',
                                      'deletion_tombstones', 'access_revocations',
                                      'reconciliation_runs'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'CREATE POLICY tenant_access ON %I USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid)',
            table_name
        );
    END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE ON proactive_rules, proactive_mutes, proactive_runs,
    quiet_hours, kill_switches, deletion_tombstones, access_revocations,
    reconciliation_runs TO cue_app, cue_ingest;
GRANT SELECT, INSERT, UPDATE ON paused_events TO cue_ingest, cue_app;
GRANT UPDATE (revoked_at) ON users TO cue_app;
