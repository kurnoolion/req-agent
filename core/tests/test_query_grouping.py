"""Tests for hierarchy-based chunk grouping (Stage 4.7).

`group_chunks_by_hierarchy` clusters retrieved chunks by longest common
hierarchy_path prefix. After D-046 every chunk carries `hierarchy_path`
in metadata with the document name as the root, so adjacent groups
naturally separate by document and by section within a document.

Group score is the minimum distance across the group's chunks (best
chunk anchors the group's relevance — weak siblings don't drag).

Output is sorted by score ascending (best group first).
"""

from __future__ import annotations

from core.src.query.grouping import (
    gap_between_top_groups,
    group_chunks_by_hierarchy,
)
from core.src.query.schema import RetrievedChunk


def _chunk(chunk_id: str, hierarchy_path: list[str], score: float) -> RetrievedChunk:
    """Build a minimal RetrievedChunk for grouping tests."""
    return RetrievedChunk(
        chunk_id=chunk_id,
        text=f"text for {chunk_id}",
        metadata={"hierarchy_path": list(hierarchy_path), "req_id": chunk_id},
        similarity_score=score,
    )


# ── Single-group cases ──────────────────────────────────────────


class TestSingleGroup:
    def test_empty_input_returns_empty(self):
        assert group_chunks_by_hierarchy([]) == []

    def test_one_chunk_one_group(self):
        c = _chunk("REQ_1", ["DOC", "Section A"], 0.2)
        groups = group_chunks_by_hierarchy([c])
        assert len(groups) == 1
        assert groups[0].common_prefix == ["DOC", "Section A"]
        assert groups[0].chunks == [c]
        assert groups[0].score == 0.2

    def test_chunks_with_identical_paths_one_group(self):
        chunks = [
            _chunk("REQ_1", ["DOC", "Section A"], 0.2),
            _chunk("REQ_2", ["DOC", "Section A"], 0.3),
            _chunk("REQ_3", ["DOC", "Section A"], 0.25),
        ]
        groups = group_chunks_by_hierarchy(chunks)
        assert len(groups) == 1
        assert groups[0].common_prefix == ["DOC", "Section A"]
        assert len(groups[0].chunks) == 3

    def test_score_is_min_distance(self):
        chunks = [
            _chunk("REQ_1", ["DOC", "Sec"], 0.45),
            _chunk("REQ_2", ["DOC", "Sec"], 0.10),  # best
            _chunk("REQ_3", ["DOC", "Sec"], 0.30),
        ]
        groups = group_chunks_by_hierarchy(chunks)
        assert groups[0].score == 0.10


# ── Multi-group cases ──────────────────────────────────────────


class TestMultipleGroups:
    def test_two_documents_two_groups(self):
        chunks = [
            _chunk("R1", ["DOC_A", "Sec1"], 0.2),
            _chunk("R2", ["DOC_B", "Sec1"], 0.3),
        ]
        groups = group_chunks_by_hierarchy(chunks)
        assert len(groups) == 2
        # Sorted by score ascending → DOC_A group first
        assert groups[0].common_prefix == ["DOC_A", "Sec1"]
        assert groups[1].common_prefix == ["DOC_B", "Sec1"]

    def test_same_doc_different_sections_share_doc_prefix(self):
        chunks = [
            _chunk("R1", ["DOC", "Sec1", "A"], 0.2),
            _chunk("R2", ["DOC", "Sec2", "B"], 0.3),
        ]
        groups = group_chunks_by_hierarchy(chunks)
        # Both share only "DOC"; grouped together with that as LCP.
        assert len(groups) == 1
        assert groups[0].common_prefix == ["DOC"]
        assert len(groups[0].chunks) == 2

    def test_three_documents_three_groups(self):
        chunks = [
            _chunk("R1", ["DOC_A"], 0.5),
            _chunk("R2", ["DOC_B"], 0.1),  # best
            _chunk("R3", ["DOC_C"], 0.3),
        ]
        groups = group_chunks_by_hierarchy(chunks)
        assert len(groups) == 3
        # Sorted ascending → DOC_B (0.1) first
        assert groups[0].common_prefix == ["DOC_B"]
        assert groups[0].score == 0.1
        assert groups[1].common_prefix == ["DOC_C"]
        assert groups[2].common_prefix == ["DOC_A"]

    def test_groups_sorted_by_min_distance(self):
        chunks = [
            _chunk("R1", ["DOC_A"], 0.4),
            _chunk("R2", ["DOC_A"], 0.5),
            _chunk("R3", ["DOC_B"], 0.2),
            _chunk("R4", ["DOC_B"], 0.3),
        ]
        groups = group_chunks_by_hierarchy(chunks)
        assert len(groups) == 2
        # DOC_B has min 0.2 → first
        assert groups[0].common_prefix == ["DOC_B"]
        assert groups[0].score == 0.2
        assert groups[1].score == 0.4


# ── Common-prefix correctness ──────────────────────────────────


class TestCommonPrefixComputation:
    def test_lcp_within_group_is_full_path_when_all_identical(self):
        chunks = [
            _chunk("R1", ["DOC", "S1", "Sub"], 0.2),
            _chunk("R2", ["DOC", "S1", "Sub"], 0.25),
        ]
        groups = group_chunks_by_hierarchy(chunks)
        assert groups[0].common_prefix == ["DOC", "S1", "Sub"]

    def test_lcp_shrinks_to_shorter_when_paths_diverge(self):
        chunks = [
            _chunk("R1", ["DOC", "S1", "A"], 0.2),
            _chunk("R2", ["DOC", "S1", "B"], 0.25),
        ]
        groups = group_chunks_by_hierarchy(chunks)
        assert groups[0].common_prefix == ["DOC", "S1"]

    def test_lcp_handles_different_lengths(self):
        chunks = [
            _chunk("R1", ["DOC", "S1"], 0.2),
            _chunk("R2", ["DOC", "S1", "deeper"], 0.25),
        ]
        groups = group_chunks_by_hierarchy(chunks)
        # Both share ["DOC", "S1"] (the shorter one is fully contained)
        assert groups[0].common_prefix == ["DOC", "S1"]

    def test_no_common_prefix_means_separate_groups(self):
        chunks = [
            _chunk("R1", ["DOC_A"], 0.2),
            _chunk("R2", ["DOC_B"], 0.25),
        ]
        groups = group_chunks_by_hierarchy(chunks)
        assert len(groups) == 2


# ── Representative titles ──────────────────────────────────────


class TestRepresentativeTitles:
    def test_titles_are_leaf_segments_outside_common_prefix(self):
        chunks = [
            _chunk("R1", ["DOC", "Sec", "Attach"], 0.2),
            _chunk("R2", ["DOC", "Sec", "Detach"], 0.3),
        ]
        groups = group_chunks_by_hierarchy(chunks)
        assert groups[0].common_prefix == ["DOC", "Sec"]
        # Titles distinguish chunks within group (sorted by path,
        # so Attach comes first, then Detach).
        assert "Attach" in groups[0].representative_titles
        assert "Detach" in groups[0].representative_titles

    def test_titles_capped_to_max(self):
        chunks = [
            _chunk(f"R{i}", ["DOC", f"Section{i}"], 0.2)
            for i in range(10)
        ]
        groups = group_chunks_by_hierarchy(chunks, max_representative_titles=3)
        assert len(groups[0].representative_titles) == 3

    def test_titles_dedupe(self):
        # Two chunks with identical leaf segments — title appears once.
        chunks = [
            _chunk("R1", ["DOC", "Sec", "Attach"], 0.2),
            _chunk("R2", ["DOC", "Sec", "Attach"], 0.3),
        ]
        groups = group_chunks_by_hierarchy(chunks)
        # When every chunk shares the full path, common_prefix
        # consumes the leaf so the title fallback uses path[-1].
        # Dedup ensures it appears exactly once.
        assert groups[0].representative_titles.count("Attach") == 1


# ── Backward compatibility ─────────────────────────────────────


class TestBackwardCompat:
    def test_chunks_without_hierarchy_path_form_unknown_group(self):
        """Pre-D-046 chunks have no hierarchy_path metadata; they
        cluster into a sentinel group with empty common_prefix."""
        c = RetrievedChunk(chunk_id="legacy", text="...",
                           metadata={"req_id": "X"}, similarity_score=0.4)
        groups = group_chunks_by_hierarchy([c])
        assert len(groups) == 1
        assert groups[0].common_prefix == []
        assert groups[0].chunks == [c]

    def test_mixed_modern_and_legacy_chunks(self):
        modern = _chunk("R1", ["DOC"], 0.2)
        legacy = RetrievedChunk(chunk_id="L1", text="...",
                                metadata={}, similarity_score=0.6)
        groups = group_chunks_by_hierarchy([modern, legacy])
        assert len(groups) == 2
        # Modern (0.2) ranks before legacy (0.6).
        assert groups[0].common_prefix == ["DOC"]
        assert groups[1].common_prefix == []

    def test_hierarchy_path_as_string_treated_as_single_segment(self):
        """Defensive: if metadata accidentally stores a string instead
        of a list, treat it as a one-element path."""
        c = RetrievedChunk(chunk_id="R1", text="...",
                           metadata={"hierarchy_path": "DOC"},
                           similarity_score=0.2)
        groups = group_chunks_by_hierarchy([c])
        assert groups[0].common_prefix == ["DOC"]


# ── Determinism ────────────────────────────────────────────────


class TestDeterminism:
    def test_same_input_produces_same_output(self):
        chunks = [
            _chunk("R3", ["DOC_A", "Sec"], 0.3),
            _chunk("R1", ["DOC_A", "Sec"], 0.1),
            _chunk("R2", ["DOC_A", "Sec"], 0.2),
        ]
        g1 = group_chunks_by_hierarchy(chunks)
        g2 = group_chunks_by_hierarchy(chunks)
        assert [g.common_prefix for g in g1] == [g.common_prefix for g in g2]
        assert [g.score for g in g1] == [g.score for g in g2]


# ── gap_between_top_groups ─────────────────────────────────────


class TestGapHelper:
    def test_gap_with_two_groups(self):
        chunks = [
            _chunk("R1", ["DOC_A"], 0.20),
            _chunk("R2", ["DOC_B"], 0.50),
        ]
        groups = group_chunks_by_hierarchy(chunks)
        assert gap_between_top_groups(groups) == 0.30

    def test_gap_with_one_group_is_inf(self):
        chunks = [
            _chunk("R1", ["DOC", "Sec"], 0.2),
            _chunk("R2", ["DOC", "Sec"], 0.3),
        ]
        groups = group_chunks_by_hierarchy(chunks)
        assert gap_between_top_groups(groups) == float("inf")

    def test_gap_with_empty_groups_is_inf(self):
        assert gap_between_top_groups([]) == float("inf")

    def test_gap_uses_top_two_only(self):
        chunks = [
            _chunk("R1", ["DOC_A"], 0.10),
            _chunk("R2", ["DOC_B"], 0.20),  # second-best
            _chunk("R3", ["DOC_C"], 0.90),  # third-best, ignored
        ]
        groups = group_chunks_by_hierarchy(chunks)
        assert gap_between_top_groups(groups) == 0.10
