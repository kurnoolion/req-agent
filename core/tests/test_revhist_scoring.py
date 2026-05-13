"""Tests for the signal-based revhist scorer (RevhistDetection).

Each test builds a small in-memory DocumentIR + DocumentProfile and
asserts whether ``_score_revhist_table`` clears the threshold for the
intended scenario.
"""

from __future__ import annotations

from core.src.models.document import (
    BlockType,
    ContentBlock,
    DocumentIR,
    FontInfo,
    MergedCell,
    Position,
)
from core.src.parser.structural_parser import GenericStructuralParser
from core.src.profiler.profile_schema import (
    BodyText,
    CrossReferencePatterns,
    DocumentProfile,
    HeaderFooter,
    HeadingDetection,
    HeadingLevel,
    PlanMetadata,
    RequirementIdPattern,
    RevhistDetection,
)


def _profile(**overrides) -> DocumentProfile:
    rd = RevhistDetection(enabled=True, **overrides)
    return DocumentProfile(
        profile_name="test",
        heading_detection=HeadingDetection(
            method="numbering",
            levels=[HeadingLevel(level=1, font_size_min=13.0, font_size_max=15.0, bold=True)],
            numbering_pattern=r"^(\d+(?:\.\d+)*)\s+\S",
        ),
        requirement_id=RequirementIdPattern(),
        plan_metadata=PlanMetadata(),
        header_footer=HeaderFooter(),
        cross_reference_patterns=CrossReferencePatterns(),
        body_text=BodyText(font_size_min=11.0, font_size_max=12.0),
        # Disable both legacy revhist paths so we exercise the score path
        # in isolation.
        revision_history_label_pattern="",
        revhist_table_header_pattern="",
        revhist_detection=rd,
    )


def _table(idx, headers, rows, page=1, merged=None):
    return ContentBlock(
        type=BlockType.TABLE,
        position=Position(page=page, index=idx),
        headers=headers,
        rows=rows,
        merged_cells=merged or [],
    )


def _para(idx, text, page=1):
    return ContentBlock(
        type=BlockType.PARAGRAPH,
        position=Position(page=page, index=idx),
        text=text,
        font_info=FontInfo(size=12.0),
    )


def _heading(idx, text, page=1):
    return ContentBlock(
        type=BlockType.PARAGRAPH,
        position=Position(page=page, index=idx),
        text=text,
        font_info=FontInfo(size=14.0, bold=True),
    )


def _doc(blocks):
    for i, b in enumerate(blocks):
        b.position.index = i
    return DocumentIR(source_file="t.docx", source_format="docx", content_blocks=blocks)


def _parser(profile):
    return GenericStructuralParser(profile)


# ---------------------------------------------------------------------------
# Position + vocab combo (the canonical case)
# ---------------------------------------------------------------------------

def test_score_fires_on_classic_revhist_at_doc_top():
    """Front-matter table with Rev/Author/Description/Date columns.
    Position (front-matter) + vocab (4 tokens) should clear default 0.55."""
    blocks = [
        _table(0,
               headers=["Rev.", "Author", "Description of Changes", "Date"],
               rows=[
                   ["1.0", "Alice", "Initial", "2026-01-01"],
                   ["1.1", "Bob",   "Edits",   "2026-02-01"],
                   ["2.0", "Carol", "Major",   "2026-03-01"],
               ]),
        _heading(1, "1 Introduction"),
        _para(2, "body"),
    ]
    parser = _parser(_profile())
    tree = parser.parse(_doc(blocks))
    assert tree.parse_stats.revhist_blocks_dropped == 1


def test_score_fires_on_german_style_vocab_variants():
    """Different vocabulary surface: Version | Editor | Comments | Date."""
    blocks = [
        _table(0,
               headers=["Version", "Editor", "Comments", "Date"],
               rows=[["1.0", "A", "x", "2026-01-01"]]),
        _heading(1, "1 Body"),
    ]
    tree = _parser(_profile()).parse(_doc(blocks))
    assert tree.parse_stats.revhist_blocks_dropped == 1


def test_score_fires_with_different_column_order():
    """Column order shouldn't matter — vocab is set-based."""
    blocks = [
        _table(0,
               headers=["Date", "Description", "Rev", "Author"],
               rows=[["2026-01-01", "x", "1.0", "A"]]),
        _heading(1, "1 Body"),
    ]
    tree = _parser(_profile()).parse(_doc(blocks))
    assert tree.parse_stats.revhist_blocks_dropped == 1


# ---------------------------------------------------------------------------
# Merged-cell label signal
# ---------------------------------------------------------------------------

def test_score_uses_merged_cell_text_in_vocab_match():
    """Headers alone are weak (only "Date") but the merged-cell label
    'Revision History' contributes vocab hits ('revision', 'history')."""
    blocks = [
        _table(0,
               headers=["X", "Date"],
               rows=[
                   ["1.0", "2026-01-01"],
                   ["1.1", "2026-02-01"],
               ],
               merged=[MergedCell(row=0, col=0, rowspan=1, colspan=2,
                                  text="Revision History")]),
        _heading(1, "1 Body"),
    ]
    tree = _parser(_profile()).parse(_doc(blocks))
    assert tree.parse_stats.revhist_blocks_dropped == 1


# ---------------------------------------------------------------------------
# Cell-content fingerprint
# ---------------------------------------------------------------------------

def test_score_uses_cell_fingerprints():
    """Headers are uninformative (single letters) but body rows have a
    version-shaped column and a date-shaped column — score should still
    clear when paired with front-matter position."""
    blocks = [
        _table(0,
               headers=["A", "B", "C"],
               rows=[
                   ["1.0", "foo", "2026-01-01"],
                   ["1.1", "bar", "2026-02-01"],
                   ["2.0", "baz", "2026-03-01"],
               ]),
        _heading(1, "1 Body"),
    ]
    # Position (0.25) + cell-fingerprint (full 0.25) = 0.50 → below default
    # threshold 0.55. Lower threshold for this test to confirm the cell
    # signal contributes.
    tree = _parser(_profile(threshold=0.45)).parse(_doc(blocks))
    assert tree.parse_stats.revhist_blocks_dropped == 1


# ---------------------------------------------------------------------------
# Negative cases — don't false-positive
# ---------------------------------------------------------------------------

def test_score_skips_non_revhist_table_in_body():
    """A reference table mid-document (no revhist vocab, no front-matter
    position) should not be dropped."""
    blocks = [
        _heading(0, "1 Introduction"),
        _para(1, "body"),
        _heading(2, "2 Reference"),
        _para(3, "see table below"),
        _table(4,
               headers=["Parameter", "Value", "Unit"],
               rows=[["X", "5", "ms"], ["Y", "10", "s"]]),
        _heading(5, "3 Next"),
    ] + [_para(i, f"filler {i}") for i in range(6, 30)]
    tree = _parser(_profile()).parse(_doc(blocks))
    assert tree.parse_stats.revhist_blocks_dropped == 0


def test_score_disabled_by_default():
    """Default-built RevhistDetection has enabled=False — score path
    never fires unless the profile opts in."""
    rd = RevhistDetection()  # default
    assert rd.enabled is False


# ---------------------------------------------------------------------------
# Consume continuation
# ---------------------------------------------------------------------------

def test_score_armed_revhist_consumes_following_tables():
    """Once the scorer fires, the same consume-until-next-paragraph
    state activates — subsequent table slices also drop."""
    blocks = [
        _table(0,
               headers=["Rev.", "Author", "Description", "Date"],
               rows=[["1.0", "A", "x", "2026-01-01"]]),
        # Continuation slice on page 2 (no header — wouldn't score on its own).
        _table(1, headers=[], rows=[["1.1", "B", "y", "2026-02-01"]], page=2),
        _heading(2, "1 Introduction", page=2),
    ]
    tree = _parser(_profile()).parse(_doc(blocks))
    assert tree.parse_stats.revhist_blocks_dropped == 2
