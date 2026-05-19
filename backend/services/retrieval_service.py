"""
Hybrid retrieval helpers: Reciprocal Rank Fusion (RRF) and result merging.
"""

from __future__ import annotations

from db.base import ChunkMatch

# Standard RRF constant (Cormack et al.)
RRF_K_DEFAULT = 60


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    *,
    k: int = RRF_K_DEFAULT,
    limit: int | None = None,
) -> list[str]:
    """
    Merge multiple ranked lists of chunk IDs using Reciprocal Rank Fusion.

    score(d) = sum over each list L: 1 / (k + rank_L(d))
    """
    if not ranked_lists:
        return []

    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)

    ordered = sorted(scores.keys(), key=lambda item_id: scores[item_id], reverse=True)
    if limit is not None:
        return ordered[:limit]
    return ordered


def merge_chunk_matches(
    ranked_ids: list[str],
    matches_by_id: dict[str, ChunkMatch],
) -> list[ChunkMatch]:
    """Return ChunkMatch objects in fused rank order, skipping unknown IDs."""
    merged: list[ChunkMatch] = []
    for chunk_id in ranked_ids:
        match = matches_by_id.get(chunk_id)
        if match is not None:
            merged.append(match)
    return merged
