-- Enable vector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Drop and recreate documents table with consolidated schema
DROP TABLE IF EXISTS document_chunks;
DROP TABLE IF EXISTS documents;

CREATE TABLE documents (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  file_name TEXT,
  status VARCHAR(50) DEFAULT 'uploaded',
  chunks JSONB DEFAULT '{"total": 0, "processed": 0}',
  error JSONB,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Create document_chunks table
CREATE TABLE document_chunks (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  document_id UUID REFERENCES documents(id),
  chunk_text TEXT,
  embedding vector(3072),
  created_at TIMESTAMP DEFAULT NOW()
);

-- Vector search function
CREATE OR REPLACE FUNCTION match_chunks(
  query_embedding vector(3072),
  match_count int DEFAULT 5,
  filter_document_id uuid DEFAULT NULL
)
RETURNS TABLE (
  id uuid,
  chunk_text text,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    document_chunks.id,
    document_chunks.chunk_text,
    1 - (document_chunks.embedding <=> query_embedding) AS similarity
  FROM document_chunks
  WHERE (filter_document_id IS NULL OR document_chunks.document_id = filter_document_id)
  ORDER BY document_chunks.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;
