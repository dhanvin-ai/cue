-- The ingest worker checks connector status before committing an event.
GRANT SELECT ON connector_connections TO cue_ingest;
