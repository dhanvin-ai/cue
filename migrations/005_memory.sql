-- Source permissions are copied onto every derived record. The API role can only read.
CREATE TABLE user_principals (
    tenant_id uuid NOT NULL,
    firebase_uid text NOT NULL,
    principal text NOT NULL,
    PRIMARY KEY (tenant_id, firebase_uid, principal),
    FOREIGN KEY (tenant_id, firebase_uid) REFERENCES users(tenant_id, firebase_uid)
);

CREATE TABLE identity_claims (
    tenant_id uuid NOT NULL,
    alias text NOT NULL,
    firebase_uid text NOT NULL,
    PRIMARY KEY (tenant_id, alias),
    FOREIGN KEY (tenant_id, firebase_uid) REFERENCES users(tenant_id, firebase_uid)
);

CREATE TABLE identity_entity_map (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    from_id uuid NOT NULL,
    to_id uuid NOT NULL,
    PRIMARY KEY (tenant_id, from_id)
);

CREATE TABLE memory_documents (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    event_id text NOT NULL,
    source text NOT NULL,
    type text NOT NULL,
    occurred_at timestamptz NOT NULL,
    actors text[] NOT NULL,
    objects text[] NOT NULL,
    facts jsonb NOT NULL DEFAULT '{}',
    text text NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    visibility text NOT NULL CHECK (visibility IN ('public', 'restricted')),
    principals text[] NOT NULL,
    raw_ref text NOT NULL,
    source_url text,
    vector_indexed_at timestamptz,
    PRIMARY KEY (tenant_id, event_id)
);
CREATE INDEX memory_documents_search_idx ON memory_documents USING gin (search_vector);
CREATE INDEX memory_documents_time_idx ON memory_documents (tenant_id, occurred_at DESC);
CREATE INDEX memory_documents_principals_idx ON memory_documents USING gin (principals);

CREATE TABLE memory_edges (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    event_id text NOT NULL,
    source_entity text NOT NULL,
    predicate text NOT NULL,
    target text NOT NULL,
    target_label text,
    valid_from timestamptz NOT NULL,
    valid_to timestamptz,
    visibility text NOT NULL CHECK (visibility IN ('public', 'restricted')),
    principals text[] NOT NULL,
    PRIMARY KEY (tenant_id, event_id, source_entity, predicate, target),
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE INDEX memory_edges_source_idx ON memory_edges (tenant_id, source_entity, predicate, valid_from DESC);
CREATE INDEX memory_edges_target_idx ON memory_edges (tenant_id, target, predicate, valid_from DESC);
CREATE INDEX memory_edges_principals_idx ON memory_edges USING gin (principals);

CREATE TABLE memory_summaries (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    id uuid NOT NULL,
    period text NOT NULL CHECK (period IN ('day', 'week', 'month', 'year')),
    period_start date NOT NULL,
    scope text NOT NULL,
    visibility text NOT NULL CHECK (visibility IN ('public', 'restricted')),
    principals text[] NOT NULL,
    text text NOT NULL,
    event_count integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX memory_summaries_period_idx ON memory_summaries (tenant_id, period, period_start DESC);
CREATE INDEX memory_summaries_principals_idx ON memory_summaries USING gin (principals);

CREATE TABLE memory_summary_sources (
    tenant_id uuid NOT NULL,
    summary_id uuid NOT NULL,
    event_id text NOT NULL,
    PRIMARY KEY (tenant_id, summary_id, event_id),
    FOREIGN KEY (tenant_id, summary_id) REFERENCES memory_summaries(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, event_id) REFERENCES memory_documents(tenant_id, event_id)
);

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['user_principals', 'identity_claims', 'identity_entity_map',
                                      'memory_documents', 'memory_edges',
                                      'memory_summaries', 'memory_summary_sources'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'CREATE POLICY tenant_access ON %I USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid)',
            table_name
        );
    END LOOP;
END $$;

GRANT SELECT ON user_principals, identity_claims, identity_entity_map,
                memory_documents, memory_edges, memory_summaries,
                memory_summary_sources TO cue_app;
GRANT SELECT ON identity_claims, identity_entity_map TO cue_ingest;
GRANT INSERT, UPDATE ON identity_entity_map TO cue_ingest;
GRANT UPDATE (entity_id) ON entity_aliases TO cue_ingest;
GRANT SELECT, INSERT, UPDATE ON memory_documents, memory_edges, memory_summaries,
                                memory_summary_sources TO cue_ingest;
GRANT DELETE ON memory_summary_sources TO cue_ingest;
