-- Durable session storage.
-- Sessions and their bound document IDs are persisted in PostgreSQL so that
-- session state survives backend restarts and is shared across Uvicorn workers.

CREATE TABLE IF NOT EXISTS sessions (
  id VARCHAR(255) PRIMARY KEY,
  tenant_id VARCHAR(255),
  created_at TIMESTAMP DEFAULT NOW(),
  last_active TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_tenant_id ON sessions(tenant_id);

-- Join table tracking which documents are bound to each session.
CREATE TABLE IF NOT EXISTS session_documents (
  session_id VARCHAR(255) NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  document_id VARCHAR(255) NOT NULL,
  PRIMARY KEY (session_id, document_id)
);
