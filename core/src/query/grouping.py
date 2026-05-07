"""Hierarchy-based chunk grouping (Stage 4.7).

Clusters retrieved chunks by longest common `hierarchy_path` prefix
(stored in chunk metadata per D-046). Two chunks share a group iff they
share at least one path level — i.e. they came from the same document.
Chunks deeper into the same section form their own sub-groups when
that produces a stricter (longer) common prefix shared by ≥2 chunks.

Algorithm — greedy LCP clustering:

  1. Sort chunks by their hierarchy_path (alphabetical / lexicographic).
     Adjacent chunks then share the maximum possible prefix.
  2. Walk pairwise: each chunk either extends the current group's
     common prefix (when LCP ≥ doc-root level) or starts a new group.
  3. After clustering, each group's `common_prefix` is the LCP across
     ALL its chunks (not just adjacent pairs — the walk preserves this
     invariant because adjacent LCP is monotonic on a sorted list).
  4. Group score = min `similarity_score` of any chunk in the group.

Singleton groups (one chunk, common_prefix = that chunk's full path)
are valid output. Chunks with empty hierarchy_path land in a sentinel
"unknown" group with `common_prefix = []` — possible only on legacy
vectorstores that predate D-046; back-compat preserved.
"""

from __future__ import annotations

from typing import Iterable

from core.src.query.schema import ChunkGroup, RetrievedChunk


_DEFAULT_REPRESENTATIVE_TITLES = 3
"""Cap on `representative_titles` per group — three titles fit a UX
card without overflow; chunks beyond surface as "+N more"."""


def group_chunks_by_hierarchy(
    chunks: list[RetrievedChunk],
    *,
    max_representative_titles: int = _DEFAULT_REPRESENTATIVE_TITLES,
) -> list[ChunkGroup]:
    """Cluster chunks by longest-common hierarchy-path prefix.

    Args:
        chunks: Retrieved chunks (in retrieval-rank order).
        max_representative_titles: Max titles per group's UX card.

    Returns:
        List of `ChunkGroup`, sorted by `score` ascending (best group
        first — lower distance = higher relevance). Empty list if
        `chunks` is empty.

    Properties:
      - **Stable across reruns.** Sort key is the path tuple, ties
        broken by chunk_id; deterministic for identical input.
      - **Single-group fallback** when every chunk shares the full
        `hierarchy_path` (typical for narrowly-targeted queries).
      - **Sentinel "unknown" group** for chunks with empty hierarchy
        (back-compat for pre-D-046 stores). Such chunks cluster into
        one group with `common_prefix = []`.
    """
    if not chunks:
        return []

    # Partition by "has hierarchy_path or not" — back-compat for
    # legacy chunks. Modern (D-046+) chunks always carry a path with
    # at least the document root, so the unknown bucket is empty in
    # practice for fresh vectorstores.
    with_path: list[RetrievedChunk] = []
    without_path: list[RetrievedChunk] = []
    for c in chunks:
        if _path_of(c):
            with_path.append(c)
        else:
            without_path.append(c)

    groups: list[ChunkGroup] = []

    # Sort by path tuple → adjacent chunks share maximum prefix.
    # Tie-break on chunk_id so the sort is fully deterministic.
    with_path.sort(key=lambda c: (_path_of(c), c.chunk_id))

    # Greedy walk: extend current group while LCP with running prefix
    # is non-empty (>= 1 path level), else flush and start new.
    current: list[RetrievedChunk] = []
    current_prefix: list[str] = []

    for c in with_path:
        cpath = _path_of(c)
        if not current:
            current = [c]
            current_prefix = list(cpath)
            continue
        new_prefix = _lcp(current_prefix, cpath)
        if new_prefix:
            # Extend the group; running prefix shrinks to the LCP.
            current.append(c)
            current_prefix = new_prefix
        else:
            # No shared prefix at all → flush and start new group.
            groups.append(_finalize_group(
                current, current_prefix, max_representative_titles,
            ))
            current = [c]
            current_prefix = list(cpath)

    if current:
        groups.append(_finalize_group(
            current, current_prefix, max_representative_titles,
        ))

    if without_path:
        groups.append(_finalize_group(
            without_path, [], max_representative_titles,
        ))

    # Best (lowest distance) first.
    groups.sort(key=lambda g: g.score)
    return groups


def gap_between_top_groups(groups: list[ChunkGroup]) -> float:
    """Distance between the top two groups' scores.

    Returns:
        `groups[1].score - groups[0].score` when ≥2 groups exist.
        Positive — groups are sorted ascending by score, so a larger
        return value means a clearer gap.
        Returns `float('inf')` when fewer than 2 groups exist (no
        ambiguity possible — auto-commit is trivially correct).

    Used by Stage 4.7 to decide auto-commit vs disambiguation: when
    `gap > gap_threshold` the top group dominates; below the threshold
    the system surfaces both groups to the user.
    """
    if len(groups) < 2:
        return float("inf")
    return groups[1].score - groups[0].score


# ── Internal helpers ─────────────────────────────────────────────


def _path_of(chunk: RetrievedChunk) -> tuple[str, ...]:
    """Read the chunk's hierarchy_path as a tuple. Returns () for
    legacy chunks without the field."""
    raw = chunk.metadata.get("hierarchy_path", []) or []
    if isinstance(raw, str):
        return (raw,)
    return tuple(str(s) for s in raw)


def _lcp(a: Iterable[str], b: Iterable[str]) -> list[str]:
    """Longest common prefix of two path sequences."""
    out: list[str] = []
    for x, y in zip(a, b):
        if x != y:
            break
        out.append(x)
    return out


def _finalize_group(
    chunks: list[RetrievedChunk],
    common_prefix: list[str],
    max_titles: int,
) -> ChunkGroup:
    """Build a ChunkGroup from accumulated chunks + their LCP."""
    # Score = min distance — best chunk in the group anchors the
    # group's relevance. See ChunkGroup.score docstring (D-049 rationale).
    score = min((c.similarity_score for c in chunks), default=0.0)

    # Representative titles: take the first `max_titles` distinct
    # rightmost-non-empty-path-element entries. These are the most
    # specific path segments — typically the leaf section title.
    titles: list[str] = []
    seen: set[str] = set()
    for c in chunks:
        path = _path_of(c)
        # Pick the deepest non-empty segment that ISN'T already part
        # of the common prefix (so the title differentiates the chunk
        # from its siblings within the group).
        leaf = ""
        for seg in reversed(path):
            if seg and seg not in common_prefix:
                leaf = seg
                break
        if not leaf and path:
            leaf = path[-1]
        if leaf and leaf not in seen:
            titles.append(leaf)
            seen.add(leaf)
        if len(titles) >= max_titles:
            break

    return ChunkGroup(
        common_prefix=list(common_prefix),
        chunks=chunks,
        score=score,
        representative_titles=titles,
    )
