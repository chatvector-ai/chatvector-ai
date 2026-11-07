"""Pure-Python retrieval metrics: recall@k, MRR, nDCG@k, packed presence.

No third-party numerics dependency is used — none is present in
requirements.txt and these are small enough not to warrant adding one.
"""

from __future__ import annotations

import math

RelevantKey = str | tuple[str, int]


def recall_at_k(
    ranked_keys: list[RelevantKey], relevant_keys: set[RelevantKey], k: int
) -> float:
    """Fraction of relevant keys present in the top-k ranked keys."""
    if not relevant_keys:
        return 0.0
    top_k = set(ranked_keys[:k])
    return len(top_k & relevant_keys) / len(relevant_keys)


def mrr(ranked_keys: list[RelevantKey], relevant_keys: set[RelevantKey]) -> float:
    """Reciprocal rank of the first relevant hit; 0.0 if none found."""
    for rank, key in enumerate(ranked_keys, start=1):
        if key in relevant_keys:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    ranked_keys: list[RelevantKey], relevant_keys: set[RelevantKey], k: int
) -> float:
    """Binary-relevance nDCG@k (DCG normalized by the ideal ordering's DCG)."""
    if not relevant_keys:
        return 0.0

    dcg = sum(
        1.0 / math.log2(i + 2)
        for i, key in enumerate(ranked_keys[:k])
        if key in relevant_keys
    )
    ideal_hits = min(len(relevant_keys), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg else 0.0


def packed_presence(packed_flags: list[bool]) -> float:
    """Fraction of relevant chunks whose packed flag is true.

    Not recall@k: the flags already say whether each relevant chunk is on
    the packer's inclusion list. Rank and the context string are not inputs.
    """
    if not packed_flags:
        return 0.0
    return sum(1.0 for flag in packed_flags if flag) / len(packed_flags)


def chunk_match_key(
    document_id: str | None, chunk_index: int | None
) -> RelevantKey | None:
    """Ground-truth matching key for a retrieved chunk.

    Uses ``(document_id, chunk_index)`` when the chunk index is known,
    else falls back to ``document_id`` alone — matching the dataset
    schema's ``relevant_doc_ids`` / ``relevant_chunks`` split.
    """
    if document_id is None:
        return None
    if chunk_index is None:
        return document_id
    return (document_id, chunk_index)
