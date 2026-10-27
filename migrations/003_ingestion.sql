-- The map exposes only installation routing to the ingest role. It is maintained by admin setup.
CREATE TABLE github_installation_map (
    installation_id bigint PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    connection_id uuid NOT NULL UNIQUE REFERENCES connector_connections(id)
);
INSERT INTO github_installation_map (installation_id, tenant_id, connection_id)
SELECT external_id::bigint, tenant_id, id FROM connector_connections WHERE provider = 'github';

CREATE TABLE entities (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    id uuid NOT NULL,
    kind text NOT NULL,
    PRIMARY KEY (tenant_id, id)
);
CREATE TABLE entity_aliases (
    tenant_id uuid NOT NULL,
    alias text NOT NULL,
    entity_id uuid NOT NULL,
    PRIMARY KEY (tenant_id, alias),
    FOREIGN KEY (tenant_id, entity_id) REFERENCES entities(tenant_id, id)
);

-- A separate unique key protects duplicate deliveries across time partitions.
CREATE TABLE event_dedupe (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    event_id text NOT NULL,
    PRIMARY KEY (tenant_id, event_id)
);
CREATE TABLE event_log (
    tenant_id uuid NOT NULL,
    event_id text NOT NULL,
    occurred_at timestamptz NOT NULL,
    source text NOT NULL,
    type text NOT NULL,
    payload jsonb NOT NULL
) PARTITION BY RANGE (occurred_at);
CREATE TABLE event_log_default PARTITION OF event_log DEFAULT PARTITION BY HASH (tenant_id);
CREATE TABLE event_log_default_0 PARTITION OF event_log_default FOR VALUES WITH (MODULUS 4, REMAINDER 0);
CREATE TABLE event_log_default_1 PARTITION OF event_log_default FOR VALUES WITH (MODULUS 4, REMAINDER 1);
CREATE TABLE event_log_default_2 PARTITION OF event_log_default FOR VALUES WITH (MODULUS 4, REMAINDER 2);
CREATE TABLE event_log_default_3 PARTITION OF event_log_default FOR VALUES WITH (MODULUS 4, REMAINDER 3);
CREATE INDEX event_log_tenant_time_idx ON event_log (tenant_id, occurred_at DESC);

-- A committed event always has a pending fan-out message. Publishing is retried separately.
CREATE TABLE event_outbox (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    event_id text NOT NULL,
    payload jsonb NOT NULL,
    published_at timestamptz,
    PRIMARY KEY (tenant_id, event_id)
);
CREATE INDEX event_outbox_pending_idx ON event_outbox (tenant_id, event_id) WHERE published_at IS NULL;

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['entities', 'entity_aliases', 'event_dedupe', 'event_log', 'event_outbox'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'CREATE POLICY tenant_access ON %I USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid)',
            table_name
        );
    END LOOP;
END $$;

GRANT USAGE ON SCHEMA public TO cue_ingest;
GRANT SELECT ON github_installation_map TO cue_ingest;
GRANT SELECT, INSERT ON entities, entity_aliases, event_dedupe, event_log, event_outbox TO cue_ingest;
GRANT UPDATE (published_at) ON event_outbox TO cue_ingest;
