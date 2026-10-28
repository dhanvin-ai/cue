-- Only trusted operator setup can bind a vendor identity to a Cue tenant.
CREATE TABLE source_bindings (
    provider text NOT NULL CHECK (provider IN ('gmail', 'calendar', 'slack', 'linear', 'recall')),
    external_id text NOT NULL,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    connection_id uuid NOT NULL UNIQUE REFERENCES connector_connections(id),
    PRIMARY KEY (provider, external_id)
);
GRANT SELECT ON source_bindings TO cue_ingest;
