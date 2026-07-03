-- API key authentication and tenant isolation
--
-- Creates persistent tenant and API key tables.
-- Adds tenant_id to documents for row-level isolation.
-- Rollback-safe: all statements use IF NOT EXISTS / IF EXISTS guards.

CREATE TABLE IF NOT EXISTS tenants (
    id          VARCHAR(255) PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    created_at  TIMESTAMP    DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS api_keys (
    id          UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id   VARCHAR(255) NOT NULL REFERENCES tenants(id),
    prefix      VARCHAR(16)  NOT NULL UNIQUE,
    key_hash    VARCHAR(64)  NOT NULL,
    status      VARCHAR(50)  NOT NULL DEFAULT 'active',
    created_at  TIMESTAMP    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_prefix    ON api_keys(prefix);
CREATE INDEX IF NOT EXISTS idx_api_keys_tenant_id ON api_keys(tenant_id);

ALTER TABLE documents ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(255);

CREATE INDEX IF NOT EXISTS idx_documents_tenant_id ON documents(tenant_id);
