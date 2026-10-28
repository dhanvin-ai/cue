-- Phase 7: meeting sessions, live transcript, speaker mapping, replies, and notes.
-- Meeting ACLs mirror the connector ACL: every attendee's verified email principal.
CREATE TABLE meeting_sessions (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    id uuid NOT NULL,
    bot_id text,
    meeting_url text NOT NULL,
    title text,
    owner_uid text NOT NULL,
    status text NOT NULL CHECK (status IN ('joining', 'live', 'ended')),
    visibility text NOT NULL DEFAULT 'restricted' CHECK (visibility IN ('public', 'restricted')),
    principals text[] NOT NULL DEFAULT '{}',
    disclosure text NOT NULL,
    consent_announced_at timestamptz,
    started_at timestamptz,
    ended_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, bot_id),
    FOREIGN KEY (tenant_id, owner_uid) REFERENCES users(tenant_id, firebase_uid)
);
CREATE INDEX meeting_sessions_status_idx ON meeting_sessions (tenant_id, status, created_at DESC);

CREATE TABLE meeting_participants (
    tenant_id uuid NOT NULL,
    meeting_id uuid NOT NULL,
    participant_id text NOT NULL,
    display_name text,
    email text,
    firebase_uid text,
    kind text NOT NULL CHECK (kind IN ('attendee', 'unknown')),
    PRIMARY KEY (tenant_id, meeting_id, participant_id),
    FOREIGN KEY (tenant_id, meeting_id) REFERENCES meeting_sessions(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, firebase_uid) REFERENCES users(tenant_id, firebase_uid)
);

-- Diarized speaker IDs stay stable; unavailable identities remain explicitly unknown.
CREATE TABLE meeting_speaker_map (
    tenant_id uuid NOT NULL,
    meeting_id uuid NOT NULL,
    speaker_id text NOT NULL,
    participant_id text,
    firebase_uid text,
    label text NOT NULL CHECK (label IN ('known', 'unknown')),
    confidence real,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, meeting_id, speaker_id),
    FOREIGN KEY (tenant_id, meeting_id) REFERENCES meeting_sessions(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, meeting_id, participant_id)
        REFERENCES meeting_participants(tenant_id, meeting_id, participant_id)
);

CREATE TABLE meeting_transcript_segments (
    tenant_id uuid NOT NULL,
    meeting_id uuid NOT NULL,
    position integer NOT NULL,
    segment_index text NOT NULL,
    speaker_id text NOT NULL,
    text text NOT NULL,
    started_at timestamptz NOT NULL,
    ended_at timestamptz NOT NULL,
    is_final boolean NOT NULL DEFAULT true,
    endpoint boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, meeting_id, position),
    UNIQUE (tenant_id, meeting_id, segment_index),
    FOREIGN KEY (tenant_id, meeting_id) REFERENCES meeting_sessions(tenant_id, id) ON DELETE CASCADE,
    CHECK (ended_at >= started_at)
);

CREATE TABLE meeting_notes (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    meeting_id uuid NOT NULL,
    summary text NOT NULL,
    decisions jsonb NOT NULL DEFAULT '[]',
    action_items jsonb NOT NULL DEFAULT '[]',
    visibility text NOT NULL CHECK (visibility IN ('public', 'restricted')),
    principals text[] NOT NULL,
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, meeting_id),
    FOREIGN KEY (tenant_id, meeting_id) REFERENCES meeting_sessions(tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX meeting_notes_principals_idx ON meeting_notes USING gin (principals);

CREATE TABLE meeting_note_sources (
    tenant_id uuid NOT NULL,
    note_id uuid NOT NULL,
    meeting_id uuid NOT NULL,
    position integer NOT NULL,
    quote text NOT NULL,
    PRIMARY KEY (tenant_id, note_id, position),
    FOREIGN KEY (tenant_id, note_id) REFERENCES meeting_notes(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, meeting_id, position)
        REFERENCES meeting_transcript_segments(tenant_id, meeting_id, position) ON DELETE CASCADE
);

CREATE TABLE meeting_replies (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    meeting_id uuid NOT NULL,
    task_id uuid,
    speaker_id text NOT NULL,
    request_text text NOT NULL,
    answer text NOT NULL,
    status text NOT NULL CHECK (status IN ('streaming', 'completed', 'interrupted')),
    chunks_sent integer NOT NULL DEFAULT 0,
    cutoff_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, meeting_id) REFERENCES meeting_sessions(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, task_id) REFERENCES agent_tasks(tenant_id, id)
);

-- Durable publication, matching the event outbox pattern.
CREATE TABLE meeting_note_deliveries (
    tenant_id uuid NOT NULL,
    note_id uuid NOT NULL,
    destination text NOT NULL CHECK (destination IN ('slack', 'email')),
    target text NOT NULL,
    payload jsonb NOT NULL,
    published_at timestamptz,
    PRIMARY KEY (tenant_id, note_id, destination, target),
    FOREIGN KEY (tenant_id, note_id) REFERENCES meeting_notes(tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX meeting_note_deliveries_pending_idx
    ON meeting_note_deliveries (tenant_id, note_id) WHERE published_at IS NULL;

-- Meeting requests use the same task and approval machinery as every other channel.
ALTER TABLE agent_tasks DROP CONSTRAINT agent_tasks_source_check;
ALTER TABLE agent_tasks ADD CONSTRAINT agent_tasks_source_check
    CHECK (source IN ('slack', 'email', 'web', 'schedule', 'meeting'));

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['meeting_sessions', 'meeting_participants',
                                      'meeting_speaker_map', 'meeting_transcript_segments',
                                      'meeting_notes', 'meeting_note_sources', 'meeting_replies',
                                      'meeting_note_deliveries'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'CREATE POLICY tenant_access ON %I USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid)',
            table_name
        );
    END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE ON meeting_sessions, meeting_participants, meeting_speaker_map,
    meeting_transcript_segments, meeting_notes, meeting_note_sources, meeting_replies,
    meeting_note_deliveries TO cue_app;
GRANT SELECT ON meeting_sessions, meeting_transcript_segments, meeting_notes TO cue_ingest;
GRANT UPDATE (published_at) ON meeting_note_deliveries TO cue_ingest;
