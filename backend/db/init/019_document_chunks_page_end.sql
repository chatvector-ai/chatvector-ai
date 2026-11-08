-- Last page that contains chunk text for PDF page-span citations (issue 652).
--
-- EXISTING INSTALLATIONS
-- Apply manually when upgrading:
--   psql "$DATABASE_URL" -f backend/db/init/019_document_chunks_page_end.sql
--
-- Rollback:
--   ALTER TABLE document_chunks DROP COLUMN IF EXISTS page_end;
--   DELETE FROM public.schema_migrations
--    WHERE filename = '019_document_chunks_page_end.sql';

BEGIN;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS page_end INTEGER;

INSERT INTO public.schema_migrations (filename)
VALUES ('019_document_chunks_page_end.sql')
ON CONFLICT (filename) DO NOTHING;

COMMIT;
