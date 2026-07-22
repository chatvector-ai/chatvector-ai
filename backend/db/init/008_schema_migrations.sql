-- Migration ledger for numbered SQL migrations.
--
-- This migration is the bridge for databases created before the ledger
-- existed: reaching 008 in lexical order means the files below have already
-- run, so record them together with this migration. Future migrations must
-- insert their own filename as their final operation before COMMIT.

BEGIN;

CREATE TABLE IF NOT EXISTS public.schema_migrations (
  filename TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO public.schema_migrations (filename)
VALUES
  ('001_init.sql'),
  ('002_dimensionless_vector.sql'),
  ('003_atomic_delete.sql'),
  ('004_chat_history.sql'),
  ('004_hybrid_retrieval.sql'),
  ('005_api_keys.sql'),
  ('006_tenant_fk_and_backfill.sql'),
  ('007_sessions.sql'),
  ('008_schema_migrations.sql')
ON CONFLICT (filename) DO NOTHING;

COMMIT;
