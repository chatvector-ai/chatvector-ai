-- Migration 002: remove fixed dimension from embedding column
-- Required when upgrading from a deployment that used vector(3072)
--
-- WARNING: existing embeddings are preserved but will be incompatible
-- if switching to a provider with a different embedding dimension.
-- A full re-ingest is required when changing providers.
--
-- Safe to run on a fresh database (column is already dimensionless).
-- Guard checks pg_attribute.atttypmod: -1 = dimensionless, >0 = fixed dimension.
-- Only runs ALTER when a fixed dimension is detected.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = 'document_chunks'
          AND n.nspname = 'public'
          AND a.attname = 'embedding'
          AND a.atttypmod <> -1
          AND a.attnum > 0
          AND NOT a.attisdropped
    ) THEN
        ALTER TABLE document_chunks
            ALTER COLUMN embedding TYPE vector
            USING embedding::vector;
    END IF;
END $$;
