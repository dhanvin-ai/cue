-- Tenant offboarding removes its audit rows with the tenant.
ALTER TABLE agent_audit DROP CONSTRAINT agent_audit_tenant_id_fkey;
ALTER TABLE agent_audit ADD CONSTRAINT agent_audit_tenant_id_fkey
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;
