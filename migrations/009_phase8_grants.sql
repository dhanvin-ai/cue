-- Lifecycle and reconciliation run as the API role, so it can purge every derived store.
GRANT SELECT, DELETE ON event_log, event_outbox, event_dedupe TO cue_app;
GRANT DELETE ON memory_documents, memory_edges, memory_summaries,
    memory_summary_sources TO cue_app;
GRANT DELETE ON meeting_sessions, meeting_participants, meeting_speaker_map,
    meeting_transcript_segments, meeting_notes, meeting_note_sources, meeting_replies,
    meeting_note_deliveries TO cue_app;
GRANT DELETE ON user_principals, identity_claims TO cue_app;
