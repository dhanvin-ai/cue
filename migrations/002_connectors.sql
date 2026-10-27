CREATE TABLE connector_connections (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    provider text NOT NULL,
    external_id text NOT NULL,
    secret_ref text,
    cursor text,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'error', 'disabled')),
    last_error text,
    UNIQUE (provider, external_id)
);

ALTER TABLE connector_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE connector_connections FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_access ON connector_connections
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

GRANT SELECT, UPDATE (cursor, status, last_error) ON connector_connections TO cue_app;
