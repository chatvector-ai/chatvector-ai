import pytest
from services.embedding_service import get_embedding, get_embeddings

pytestmark = pytest.mark.asyncio


async def test_get_embedding_success():
    text = "Hello world"
    embedding = await get_embedding(text)

    assert isinstance(embedding, list)
    assert len(embedding) == 3072
    assert all(isinstance(v, float) for v in embedding)


async def test_get_embeddings_batch_success():
    texts = ["Hello world", "Another sentence"]
    embeddings = await get_embeddings(texts)

    assert isinstance(embeddings, list)
    assert len(embeddings) == 2

    for emb in embeddings:
        assert isinstance(emb, list)
        assert len(emb) == 3072
        assert all(isinstance(v, float) for v in emb)


async def test_embedding_dimension_consistency():
    texts = ["short text", "longer text with more content"]
    embeddings = await get_embeddings(texts)

    dims = {len(e) for e in embeddings}
    assert dims == {3072}


async def test_embedding_fallback_on_failure(monkeypatch):
    async def always_fail(*args, **kwargs):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(
        "services.embedding_service.client.models.embed_content",
        always_fail,
    )

    texts = ["fallback test"]
    embeddings = await get_embeddings(texts)

    assert len(embeddings) == 1
    assert len(embeddings[0]) == 3072
    assert all(v == 0.0 for v in embeddings[0])
