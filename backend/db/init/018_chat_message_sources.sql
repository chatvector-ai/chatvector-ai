-- Answer-time source snapshot on assistant chat messages.
--
-- Stores the display and provenance fields used for that answer so history
-- can render the original citation after a later document replacement.
-- NULL is a pre-snapshot row. [] is a generated answer that had no sources.
--
-- EXISTING INSTALLATIONS
-- Docker volumes initialised before this file existed do not re-run it.
-- Apply manually:
--   psql "$DATABASE_URL" -f backend/db/init/018_chat_message_sources.sql
--
-- Rollback:
--   ALTER TABLE chat_messages DROP COLUMN IF EXISTS sources;
--   DELETE FROM public.schema_migrations
--    WHERE filename = '018_chat_message_sources.sql';

BEGIN;

ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS sources JSONB;

INSERT INTO public.schema_migrations (filename)
VALUES ('018_chat_message_sources.sql')
ON CONFLICT (filename) DO NOTHING;

COMMIT;
