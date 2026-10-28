-- Memory reads are auditable access events, separate from writes and approvals.
ALTER TABLE agent_audit DROP CONSTRAINT agent_audit_action_check;
ALTER TABLE agent_audit ADD CONSTRAINT agent_audit_action_check
    CHECK (action IN ('ingress', 'policy', 'tool', 'approval', 'response', 'retry',
                      'control', 'deletion', 'revocation', 'export', 'reconciliation',
                      'proactive', 'access'));
