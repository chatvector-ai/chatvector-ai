-- Hybrid retrieval: PostgreSQL full-text search on chunk text
ALTER TABLE document_chunks
  ADD COLUMN IF NOT EXISTS content_tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('english', coalesce(chunk_text, ''))) STORED;

CREATE INDEX IF NOT EXISTS idx_document_chunks_content_tsv
  ON document_chunks USING GIN (content_tsv);
