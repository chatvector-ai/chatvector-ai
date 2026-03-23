# feat: chunk metadata storage and source citation support

Closes #23, #26

## Summary

Extends the ingestion pipeline to capture rich per-chunk metadata (page
number, character offsets, chunk index) and surfaces that metadata as
traceable source citations in every chat response.

---

## What changed

### Database / schema
- `document_chunks` table gets four new columns: `chunk_index`, `page_number`, `character_offset_start`, `character_offset_end` (`db/init/001_init.sql`)
- `match_chunks` SQL RPC updated to JOIN the `documents` table and return the new columns alongside `file_name`
- ORM model (`core/models.py`) updated to match

### `db/base.py`
- New `ChunkRecord` dataclass replaces the bare `tuple[str, list[float]]` type used throughout; carries `chunk_text`, `embedding`, `chunk_index`, `page_number`, `char_offset_start`, `char_offset_end`
- All abstract method signatures updated to `list[ChunkRecord]`

### `db/sqlalchemy_service.py` + `db/supabase_service.py`
- `store_chunks_with_embeddings` writes the new metadata columns
- `find_similar_chunks` returns `file_name` from the JOIN

### `services/extraction_service.py`
- New `PageBoundary` dataclass tracks cumulative character offsets per PDF page
- New `extract_text_with_metadata()` returns `(full_text, page_boundaries)` so the pipeline knows which page each character belongs to

### `services/ingestion_pipeline.py`
- Switched from `split_text()` → `create_documents()` with `add_start_index=True` to capture LangChain character offsets
- New `_resolve_page_number()` maps a character offset to a PDF page via `PageBoundary` list
- New `_build_chunk_records()` assembles `ChunkRecord` objects with all metadata fields before the embed step

### `services/ingestion_service.py`
- Atomic ingestion path updated to build `ChunkRecord` objects with offset metadata

### `services/context_service.py`
- Each chunk is now prefixed with `[Source: <file_name>, page <N>]` before being passed to the LLM prompt, enabling traceable citations in answers

### `services/chat_service.py`
- Single and batch chat responses now include a `sources` array built from the retrieved `ChunkMatch` objects: `[{file_name, page_number, chunk_index}]`

---

## Response shape (chat)

```json
{
  "answer": "The policy states ...",
  "sources": [
    { "file_name": "policy.pdf", "page_number": 4, "chunk_index": 7 },
    { "file_name": "policy.pdf", "page_number": 5, "chunk_index": 8 }
  ]
}
```

---

## Tests

| File | What's covered |
|---|---|
| `test_ingestion_pipeline.py` | `_resolve_page_number`, `_build_chunk_records`, end-to-end `ChunkRecord` construction |
| `test_chat_service.py` | `sources` shape for single and batch responses; `None` page_number for TXT files |
| `test_upload_atomic.py` | Updated to `ChunkRecord`-based API |

---

## Test plan

- [ ] `docker compose run --rm tests` — all unit tests pass
- [ ] Upload a multi-page PDF; query it and confirm `sources` in the response includes correct `page_number` values
- [ ] Upload a TXT file; confirm `page_number` is `null` in sources (no page concept)
- [ ] Check `document_chunks` in the DB directly to verify `chunk_index`, `page_number`, and offset columns are populated
