-- Enable vector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create documents table
CREATE TABLE IF NOT EXISTS documents (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  file_name TEXT,
  status VARCHAR(50) DEFAULT 'uploaded',
  failed_stage TEXT,
  error_message TEXT,
  chunks_total INTEGER DEFAULT 0,
  chunks_processed INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Add/migrate status and progress columns for existing databases
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'documents' AND column_name = 'status'
    ) THEN
        ALTER TABLE documents ADD COLUMN status VARCHAR(50) DEFAULT 'uploaded';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'documents' AND column_name = 'failed_stage'
    ) THEN
        ALTER TABLE documents ADD COLUMN failed_stage TEXT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'documents' AND column_name = 'error_message'
    ) THEN
        ALTER TABLE documents ADD COLUMN error_message TEXT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'documents' AND column_name = 'chunks_total'
    ) THEN
        ALTER TABLE documents ADD COLUMN chunks_total INTEGER DEFAULT 0;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'documents' AND column_name = 'chunks_processed'
    ) THEN
        ALTER TABLE documents ADD COLUMN chunks_processed INTEGER DEFAULT 0;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'documents' AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE documents ADD COLUMN updated_at TIMESTAMP DEFAULT NOW();
    END IF;

    ALTER TABLE documents ALTER COLUMN status SET DEFAULT 'uploaded';
END $$;

-- Create document_chunks table
CREATE TABLE IF NOT EXISTS document_chunks (
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
