"""Tests for plan-metadata extraction (`_extract_plan_metadata`).

Verifies that patterns are matched per-paragraph — so the common
"non-greedy terminator never appears in the joined blob" case can't
gobble the rest of the document into ``plan_name``.
"""

from __future__ import annotations

from core.src.models.document import (
    BlockType,
    ContentBlock,
    DocumentIR,
    FontInfo,
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
    MetadataField,
    PlanMetadata,
    RequirementIdPattern,
)


def _profile() -> DocumentProfile:
    return DocumentProfile(
        profile_name="t",
        heading_detection=HeadingDetection(
            levels=[HeadingLevel(level=1, font_size_min=13.0, font_size_max=15.0, bold=True)],
            numbering_pattern=r"^(\d+(?:\.\d+)*)\s+\S",
        ),
        requirement_id=RequirementIdPattern(),
        plan_metadata=PlanMetadata(
            plan_name=MetadataField(
                location="first_page",
                pattern=r"Plan\s+Name:\s*(.+?)(?:\n|Plan\s+Id|$)",
            ),
            plan_id=MetadataField(
                location="first_page",
                pattern=r"Plan\s+Id:\s*(\w+)",
            ),
        ),
        header_footer=HeaderFooter(),
        cross_reference_patterns=CrossReferencePatterns(),
        body_text=BodyText(font_size_min=11.0, font_size_max=12.0),
    )


def _para(idx: int, text: str, page: int = 1) -> ContentBlock:
    return ContentBlock(
        type=BlockType.PARAGRAPH,
        position=Position(page=page, index=idx),
        text=text,
        font_info=FontInfo(size=12.0),
    )


def _doc(blocks: list[ContentBlock]) -> DocumentIR:
    for i, b in enumerate(blocks):
        b.position.index = i
    return DocumentIR(source_file="t.docx", source_format="docx",
                      content_blocks=blocks)


def _extract(blocks):
    return GenericStructuralParser(_profile())._extract_plan_metadata(_doc(blocks))


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_extract_plan_name_from_dedicated_paragraph():
    meta = _extract([
        _para(0, "Plan Name: LTE Data Retry"),
        _para(1, "Plan Id: LTEDATARETRY"),
    ])
    assert meta["plan_name"] == "LTE Data Retry"
    assert meta["plan_id"] == "LTEDATARETRY"


def test_extract_plan_name_from_combined_paragraph():
    """Real-corpus form: name and id on the same paragraph line."""
    meta = _extract([
        _para(0, "Plan Name: LTE Data Retry Plan Id: LTEDATARETRY"),
    ])
    assert meta["plan_name"] == "LTE Data Retry"
    assert meta["plan_id"] == "LTEDATARETRY"


# ---------------------------------------------------------------------------
# The bug: plan_name leaking into the TOC + body when Plan Id is missing
# ---------------------------------------------------------------------------

def test_plan_name_does_not_leak_when_plan_id_missing():
    """When the doc has 'Plan Name:' but NO 'Plan Id:' anywhere, the
    plan_name regex previously gobbled everything to end-of-doc.
    Per-paragraph scoping bounds it to the value paragraph."""
    blocks = [
        _para(0, "Plan Name: My Plan"),
        _para(1, "Table of Contents"),
        _para(2, "1 Introduction ........ 1"),
        _para(3, "2 Requirements ........ 5"),
        _para(4, "3 References ......... 99"),
    ]
    meta = _extract(blocks)
    assert meta.get("plan_name") == "My Plan"
    assert "plan_id" not in meta or meta["plan_id"] == ""


def test_plan_name_and_id_both_missing():
    """When neither field is present, both return empty (not present
    in the dict — downstream reads via .get default to '')."""
    blocks = [
        _para(0, "Random opening paragraph."),
        _para(1, "Table of Contents"),
        _para(2, "1 Introduction"),
    ]
    meta = _extract(blocks)
    assert meta.get("plan_name", "") == ""
    assert meta.get("plan_id", "") == ""


# ---------------------------------------------------------------------------
# Behavior on page=2+
# ---------------------------------------------------------------------------

def test_plan_name_only_scanned_on_page_1():
    """Plan Name written somewhere on page 2 isn't picked up."""
    blocks = [
        _para(0, "Some preamble.", page=1),
        _para(1, "Plan Name: Body Plan", page=2),
    ]
    meta = _extract(blocks)
    assert meta.get("plan_name", "") == ""


# ---------------------------------------------------------------------------
# Defensive — pattern issues
# ---------------------------------------------------------------------------

def test_uncompilable_pattern_skipped_gracefully():
    """A malformed regex in the profile shouldn't blow up extraction —
    just skip the field."""
    parser = GenericStructuralParser(_profile())
    parser.profile.plan_metadata.plan_name = MetadataField(
        location="first_page",
        pattern=r"(unclosed",   # broken regex
    )
    meta = parser._extract_plan_metadata(_doc([
        _para(0, "Plan Name: X"),
    ]))
    assert "plan_name" not in meta
