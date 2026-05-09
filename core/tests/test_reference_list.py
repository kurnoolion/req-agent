"""Tests for reference_list extraction [D-059, D-061].

Covers ``GenericStructuralParser._extract_reference_list``:
- Section detection via `reference_list_section_pattern`.
- Per-entry parsing across bracketed (`[N]`), parenthesized (`(N)`),
  and plain (`N.`) numbering variants.
- spec/title splitter heuristic.
- JSON roundtrip on `RequirementTree.reference_list_map`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.src.models.document import (
    BlockType,
    ContentBlock,
    DocumentIR,
    FontInfo,
    Position,
)
from core.src.parser.structural_parser import (
    GenericStructuralParser,
    RequirementTree,
)
from core.src.profiler.profile_schema import (
    DocumentProfile,
    HeadingDetection,
    RequirementIdPattern,
)


def _profile(**overrides) -> DocumentProfile:
    base = DocumentProfile(
        profile_name="test",
        heading_detection=HeadingDetection(
            numbering_pattern=r"^(\d+(?:\.\d+)*)\s+\S",
        ),
        requirement_id=RequirementIdPattern(pattern="VZ_REQ_[A-Z0-9_]+"),
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _ir_with_references(text: str) -> DocumentIR:
    return DocumentIR(
        source_file="t.docx",
        source_format="docx",
        content_blocks=[
            ContentBlock(
                type=BlockType.PARAGRAPH,
                position=Position(page=1, index=0),
                text="1 References",
                font_info=FontInfo(size=14.0, bold=True),
            ),
            ContentBlock(
                type=BlockType.PARAGRAPH,
                position=Position(page=1, index=1),
                text=text,
                font_info=FontInfo(size=11.0),
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Detection + per-entry parsing
# ---------------------------------------------------------------------------

class TestReferenceListDetection:
    def test_bracketed_entries(self):
        ir = _ir_with_references(
            '[1] 3GPP TS 23.401, "GPRS enhancements"\n'
            '[2] 3GPP TS 24.301, "Non-Access-Stratum protocol"\n'
        )
        tree = GenericStructuralParser(_profile()).parse(ir)
        assert tree.parse_stats.refs_extracted == 2
        assert tree.reference_list_map[1]["spec"] == "3GPP TS 23.401"
        assert tree.reference_list_map[1]["title"] == "GPRS enhancements"
        assert tree.reference_list_map[2]["spec"] == "3GPP TS 24.301"

    def test_parenthesized_entries(self):
        ir = _ir_with_references(
            '(5) 3GPP TS 24.301, §5.5.1.2.6\n'
            '(12) GSMA SGP.22 v3.0\n'
        )
        tree = GenericStructuralParser(_profile()).parse(ir)
        assert tree.parse_stats.refs_extracted == 2
        assert tree.reference_list_map[5]["spec"] == "3GPP TS 24.301"
        # No comma/quote/em-dash → entire content is spec
        assert tree.reference_list_map[12]["spec"] == "GSMA SGP.22 v3.0"
        assert "title" not in tree.reference_list_map[12]

    def test_plain_numbering(self):
        ir = _ir_with_references(
            '1. 3GPP TS 23.401\n'
            '2. 3GPP TS 24.301\n'
        )
        tree = GenericStructuralParser(_profile()).parse(ir)
        assert tree.parse_stats.refs_extracted == 2

    def test_first_occurrence_wins_on_duplicate_number(self):
        ir = _ir_with_references(
            '[1] First spec\n'
            '[1] Second spec — should be ignored\n'
        )
        tree = GenericStructuralParser(_profile()).parse(ir)
        assert tree.parse_stats.refs_extracted == 1
        assert tree.reference_list_map[1]["spec"] == "First spec"

    def test_section_section_number_recorded(self):
        ir = _ir_with_references('[1] 3GPP TS 23.401\n')
        tree = GenericStructuralParser(_profile()).parse(ir)
        assert tree.reference_list_section_number == "1"

    def test_no_matching_section_returns_empty(self):
        # "Introduction" doesn't match the references regex.
        ir = DocumentIR(
            source_file="t.docx", source_format="docx",
            content_blocks=[
                ContentBlock(
                    type=BlockType.PARAGRAPH,
                    position=Position(page=1, index=0),
                    text='1 Introduction',
                    font_info=FontInfo(size=14.0, bold=True),
                ),
                ContentBlock(
                    type=BlockType.PARAGRAPH,
                    position=Position(page=1, index=1),
                    text='[1] 3GPP TS 23.401',
                    font_info=FontInfo(size=11.0),
                ),
            ],
        )
        tree = GenericStructuralParser(_profile()).parse(ir)
        assert tree.parse_stats.refs_extracted == 0
        assert tree.reference_list_map == {}
        assert tree.reference_list_section_number == ""

    def test_disabled_via_empty_pattern(self):
        ir = _ir_with_references('[1] 3GPP TS 23.401\n')
        profile = _profile(reference_list_section_pattern="")
        tree = GenericStructuralParser(profile).parse(ir)
        assert tree.parse_stats.refs_extracted == 0


# ---------------------------------------------------------------------------
# Spec/title splitter heuristic
# ---------------------------------------------------------------------------

class TestSplitReferenceEntry:
    def test_comma_quote_split(self):
        spec, title = GenericStructuralParser._split_reference_entry(
            '3GPP TS 24.301, "Non-Access-Stratum protocol"'
        )
        assert spec == "3GPP TS 24.301"
        assert title == "Non-Access-Stratum protocol"

    def test_em_dash_split(self):
        spec, title = GenericStructuralParser._split_reference_entry(
            "ETSI TS 133 401 — Security Architecture"
        )
        assert spec == "ETSI TS 133 401"
        assert title == "Security Architecture"

    def test_no_delimiter_treats_whole_as_spec(self):
        spec, title = GenericStructuralParser._split_reference_entry(
            "GSMA SGP.22 v3.0"
        )
        assert spec == "GSMA SGP.22 v3.0"
        assert title == ""


# ---------------------------------------------------------------------------
# JSON roundtrip
# ---------------------------------------------------------------------------

class TestReferenceListMapRoundtrip:
    def test_save_load_preserves_map_and_counter(self, tmp_path: Path):
        ir = _ir_with_references(
            '[1] 3GPP TS 23.401, "GPRS enhancements"\n'
            '[5] 3GPP TS 24.301\n'
        )
        tree = GenericStructuralParser(_profile()).parse(ir)
        assert tree.parse_stats.refs_extracted == 2

        path = tmp_path / "tree.json"
        tree.save_json(path)
        tree2 = RequirementTree.load_json(path)

        # Map keys are ints after load (not strings as JSON would default)
        assert set(tree2.reference_list_map.keys()) == {1, 5}
        assert tree2.reference_list_map[1]["spec"] == "3GPP TS 23.401"
        assert tree2.parse_stats.refs_extracted == 2
        assert tree2.reference_list_section_number == "1"
