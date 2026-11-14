"""Post-merge primary checkout sync and batch git reachability reporting."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .gitrepo import GitRepo


@dataclass
class PrimarySyncResult:
    """Structured result after a GitHub merge; does not collapse GitHub and local sync."""

    github_merge_success: bool = True
    merge_sha: str = ""
    status: str = "unknown"
    primary_branch: str = ""
    primary_clean: bool = False
    primary_dirty_paths: list[str] = field(default_factory=list)
    primary_head: str = ""
    merge_sha_on_primary_head: bool = False
    upstream_main: str = ""
    origin_main: str | None = None
    origin_matches_upstream: bool = False
    primary_rebase_attempted: bool = False
    primary_rebase_succeeded: bool = False
    origin_push_attempted: bool = False
    origin_push_succeeded: bool = False
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def enrich_sync_result(result: PrimarySyncResult, git: GitRepo, merge_sha: str) -> dict[str, Any]:
    """Attach merge SHA reachability on the primary checkout after sync."""

    payload = result.to_dict()
    payload["merge_sha"] = merge_sha
    payload["github_merge_success"] = True
    if merge_sha and git.commit_exists(merge_sha):
        head = git.rev_parse(git.root)
        payload["primary_head"] = head
        reachable = git.is_ancestor(merge_sha, head)
        # A dirty primary may only receive a ref update on `origin`; do not
        # report the merge as "on" the checkout until rebase actually succeeded.
        payload["merge_sha_on_primary_head"] = bool(
            reachable and result.primary_rebase_succeeded
        )
    else:
        payload["merge_sha_on_primary_head"] = False
    return payload


def build_primary_git_snapshot(git: GitRepo, merge_shas: list[str]) -> dict[str, Any]:
    """Canonical vs primary reachability for batch completion reporting."""

    head = git.rev_parse(git.root)
    upstream = git.safe_rev_parse("upstream/main")
    origin = git.safe_rev_parse("origin/main")
    primary_vs_upstream = (
        dict(zip(("ahead", "behind"), git.ahead_behind(head, upstream), strict=True))
        if upstream
        else None
    )
    origin_vs_upstream = (
        dict(zip(("ahead", "behind"), git.ahead_behind(origin, upstream), strict=True))
        if origin and upstream
        else None
    )
    reachability: dict[str, dict[str, bool]] = {}
    for sha in merge_shas:
        if not sha:
            continue
        on_canonical = bool(upstream and git.commit_exists(sha) and git.is_ancestor(sha, upstream))
        on_primary = bool(git.commit_exists(sha) and git.is_ancestor(sha, head))
        reachability[sha] = {
            "on_canonical_main": on_canonical,
            "on_primary_head": on_primary,
        }
    all_on_primary = bool(reachability) and all(
        item["on_primary_head"] for item in reachability.values()
    )
    return {
        "primary_head": head,
        "upstream_main": upstream,
        "origin_main": origin,
        "primary_vs_upstream": primary_vs_upstream,
        "origin_vs_upstream": origin_vs_upstream,
        "origin_matches_upstream": bool(origin and upstream and origin == upstream),
        "merge_reachability": reachability,
        "all_merge_shas_on_primary_head": all_on_primary,
    }


def primary_checkout_stale(snapshot: dict[str, Any] | None, *, merged_count: int) -> bool:
    if not snapshot or merged_count == 0:
        return False
    if snapshot.get("merge_reachability"):
        return not snapshot.get("all_merge_shas_on_primary_head", False)
    primary_vs = snapshot.get("primary_vs_upstream") or {}
    if primary_vs.get("behind", 0):
        return True
    return False
