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


async def test_get_embeddings_raises_on_failure(monkeypatch):
    """Embedding failures must propagate; the zero-vector fallback is gone."""
    def always_fail(*args, **kwargs):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(
        "services.embedding_service.client.models.embed_content",
        always_fail,
    )

    with pytest.raises(RuntimeError, match="forced failure"):
        await get_embeddings(["this should raise"])


async def test_get_embeddings_splits_large_batch(monkeypatch):
    """Inputs exceeding 100 are split into sequential batches of ≤100."""
    batch_sizes: list[int] = []

    class _FakeEmbedding:
        values = [0.1] * 3072

    def fake_embed(model, contents):
        batch_sizes.append(len(contents))

        class _Result:
            embeddings = [_FakeEmbedding() for _ in contents]

        return _Result()

    monkeypatch.setattr(
        "services.embedding_service.client.models.embed_content",
        fake_embed,
    )

    texts = ["text"] * 150
    embeddings = await get_embeddings(texts)

    assert len(embeddings) == 150
    assert batch_sizes == [100, 50]
    assert all(len(e) == 3072 for e in embeddings)
