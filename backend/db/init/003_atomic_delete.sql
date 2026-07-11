-- Migration: Atomic Document Deletion RPC
-- Issue: #245
-- Description: Adds an RPC function to perform atomic deletion of a document and its chunks.
-- This ensures that no orphaned chunks remain if a network failure occurs between delete calls.
--
-- LEGACY: This RPC is retained for databases that already have it installed.
-- It is NOT called by any current runtime code path. SQLAlchemyService performs
-- atomic deletion natively via ORM transactions. Safe to leave in place.

CREATE OR REPLACE FUNCTION delete_document_atomic(target_document_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  -- 1. Delete all related chunks first to satisfy foreign key constraints
  DELETE FROM document_chunks
  WHERE document_id = target_document_id;

  -- 2. Delete the document record itself
  DELETE FROM documents
  WHERE id = target_document_id;
END;
$$;

-- SECURITY DEFINER runs with owner privileges; restrict who may invoke it.
REVOKE ALL ON FUNCTION delete_document_atomic(uuid) FROM PUBLIC;
-- Supabase exposes this RPC only via the backend (service_role). Local Postgres
-- often has no service_role role; conditional grant keeps migrations portable.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    GRANT EXECUTE ON FUNCTION delete_document_atomic(uuid) TO service_role;
  END IF;
END;
$$;
