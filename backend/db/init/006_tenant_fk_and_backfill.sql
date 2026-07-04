-- Tenant foreign key and backfill guidance
--
-- This migration adds a foreign key from documents.tenant_id → tenants.id
-- and creates a placeholder for backfilling pre-existing rows.
--
-- Rollback-safe: all statements use IF NOT EXISTS / IF EXISTS guards.
--
-- ────────────────────────────────────────────────────────────────────────────
-- EXISTING INSTALLATIONS
-- ────────────────────────────────────────────────────────────────────────────
-- If you deployed before this migration was applied, run:
--
--   docker compose exec db psql -U postgres -d postgres \
--       -f /docker-entrypoint-initdb.d/006_tenant_fk_and_backfill.sql
--
-- Before adding the FK you must ensure documents.tenant_id is non-NULL for
-- every row, or the constraint will fail.  If you have pre-existing documents
-- without a tenant_id, backfill them first:
--
--   -- Option A: assign all unowned documents to a known tenant
--   UPDATE documents
--      SET tenant_id = '<your-tenant-id>'
--    WHERE tenant_id IS NULL;
--
--   -- Option B: delete orphaned documents (irreversible)
--   DELETE FROM documents WHERE tenant_id IS NULL;
--
-- After backfilling, run this file to add the constraint.
--
-- ────────────────────────────────────────────────────────────────────────────
-- ROLLBACK
-- ────────────────────────────────────────────────────────────────────────────
-- To reverse this migration:
--
--   ALTER TABLE documents DROP CONSTRAINT IF EXISTS fk_documents_tenant_id;
--   ALTER TABLE documents ALTER COLUMN tenant_id DROP NOT NULL;
--
-- ────────────────────────────────────────────────────────────────────────────
-- NOTE on duplicate 004_* numbering
-- ────────────────────────────────────────────────────────────────────────────
-- The init directory contains 004_chat_history.sql and
-- 004_hybrid_retrieval.sql — two files sharing the same numeric prefix.
-- PostgreSQL's docker-entrypoint-initdb.d applies files in alphabetical
-- order (004_chat_history before 004_hybrid_retrieval), which is the
-- intended sequence.  Do not add additional 004_* files; use 007_* for
-- the next migration.
-- ────────────────────────────────────────────────────────────────────────────

-- Step 1: Add FK from documents.tenant_id → tenants.id.
--
-- ON DELETE SET NULL lets tenant deletion leave documents intact but
-- unowned; callers that require a valid tenant can subsequently clean up.
-- Requires that 005_api_keys.sql has already been applied.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM information_schema.table_constraints
         WHERE constraint_name = 'fk_documents_tenant_id'
           AND table_name      = 'documents'
    ) THEN
        ALTER TABLE documents
            ADD CONSTRAINT fk_documents_tenant_id
            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
            ON DELETE SET NULL;
    END IF;
END;
$$;

-- Step 2: After all rows have been backfilled (see instructions above),
-- uncomment the line below to enforce NOT NULL:
--
-- ALTER TABLE documents ALTER COLUMN tenant_id SET NOT NULL;
