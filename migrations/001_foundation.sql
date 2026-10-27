CREATE TABLE tenants (
    id uuid PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE users (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    firebase_uid text NOT NULL,
    role text NOT NULL CHECK (role IN ('admin', 'member')),
    PRIMARY KEY (tenant_id, firebase_uid)
);

CREATE TABLE principals (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    kind text NOT NULL CHECK (kind IN ('person', 'team')),
    external_id text NOT NULL,
    UNIQUE (tenant_id, kind, external_id)
);

CREATE TABLE agents (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    display_name text NOT NULL,
    email text,
    UNIQUE (tenant_id, id)
);

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_access ON tenants
    USING (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_access ON users
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE principals ENABLE ROW LEVEL SECURITY;
ALTER TABLE principals FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_access ON principals
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE agents FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_access ON agents
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

GRANT USAGE ON SCHEMA public TO cue_app;
GRANT SELECT ON tenants, users, principals, agents TO cue_app;
