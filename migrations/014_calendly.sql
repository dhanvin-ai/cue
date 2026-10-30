-- Calendly joins the operator-bound v1 sources.
ALTER TABLE source_bindings DROP CONSTRAINT source_bindings_provider_check;
ALTER TABLE source_bindings ADD CONSTRAINT source_bindings_provider_check
    CHECK (provider IN ('gmail', 'calendar', 'calendly', 'slack', 'linear', 'recall'));
