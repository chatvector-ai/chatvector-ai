-- Migration 002: remove fixed dimension from embedding column
-- Required when upgrading from a deployment that used vector(3072)
--
-- WARNING: existing embeddings are preserved but will be incompatible
-- if switching to a provider with a different embedding dimension.
-- A full re-ingest is required when changing providers.
--
-- Safe to run on a fresh database (column is already dimensionless).

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'document_chunks'
        AND column_name = 'embedding'
    ) THEN
        ALTER TABLE document_chunks
            ALTER COLUMN embedding TYPE vector
            USING embedding::vector;
    END IF;
END $$;
