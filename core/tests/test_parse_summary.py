"""Tests for ``RequirementTree.parse_summary`` — the per-doc evidence
record the parser builds for the corpus-level parse_summary.json
artifact consumed by the Parse Review Summary tab.

Three things to verify per doc:
  * Revhist evidence is captured when the pre-pass finds a label.
  * Glossary evidence is captured when ``_extract_definitions``
    matches a section — including for empty maps (so the user
    can see "matched heading, 0 entries extracted" rows).
  * Toc entry count + format_errors propagate.
"""

from __future__ import annotations

from core.src.models.document import (
    BlockType,
    ContentBlock,
    DocumentIR,
    FontInfo,
    Position,
    TextRun,
)
from core.src.parser.parse_summary import (
    CorpusSummary,
    DocSummary,
    GlossaryMatch,
    RevhistMatch,
    build_corpus_summary,
)
from core.src.parser.structural_parser import GenericStructuralParser
from core.src.profiler.profile_schema import (
    BodyText,
    CrossReferencePatterns,
    DocumentProfile,
    HeaderFooter,
    HeadingDetection,
    PlanMetadata,
    RequirementIdPattern,
    TocDetection,
)


def _docx_profile() -> DocumentProfile:
    return DocumentProfile(
        profile_name="test_docx",
        heading_detection=HeadingDetection(
            method="docx_styles",
            definitions_section_pattern=r"(?i)glossary|acronym|definition",
        ),
        requirement_id=RequirementIdPattern(
            pattern=r"VZ_REQ_[A-Z0-9_]+_\d+",
            anchor="last_run",
            normalize="upper",
        ),
        plan_metadata=PlanMetadata(),
        document_zones=[],
        header_footer=HeaderFooter(),
        cross_reference_patterns=CrossReferencePatterns(),
        body_text=BodyText(font_size_min=11.0, font_size_max=12.0),
        toc_detection=TocDetection(
            style_pattern=r"(?i)^toc\s+(\d+)$",
            entry_pattern=r"^(?P<num>[\w.]+)\t(?P<body>.+?)\t(?P<page>\d+)\s*$",
        ),
    )


def _heading_block(
    idx: int, depth: int, title: str, req_id: str, *, block_type=BlockType.HEADING
) -> ContentBlock:
    return ContentBlock(
        type=block_type,
        position=Position(page=1, index=idx),
        text=f"{title}{req_id}",
        style=f"Heading {depth}",
        level=depth if block_type == BlockType.HEADING else None,
        font_info=FontInfo(size=14.0, bold=True),
        runs=[
            TextRun(text=title, struck=False),
            TextRun(text=req_id, struck=False),
        ],
    )


def _para(idx: int, text: str) -> ContentBlock:
    return ContentBlock(
        type=BlockType.PARAGRAPH,
        position=Position(page=1, index=idx),
        text=text,
        font_info=FontInfo(size=11.0),
    )


def _doc(blocks: list[ContentBlock]) -> DocumentIR:
    for i, b in enumerate(blocks):
        b.position.index = i
    return DocumentIR(
        source_file="VOWIFI.docx",
        source_format="docx",
        mno="VZ",
        release="Feb2026",
        doc_type="requirement",
        content_blocks=blocks,
    )


def _table(idx: int, headers: list[str], rows: list[list[str]]) -> ContentBlock:
    return ContentBlock(
        type=BlockType.TABLE,
        position=Position(page=1, index=idx),
        headers=headers,
        rows=rows,
    )


# ---------------------------------------------------------------------------
# DocSummary per-doc evidence
# ---------------------------------------------------------------------------


class TestRevhistEvidence:
    def test_revhist_match_captures_label_and_table_headers(self):
        revhist_label = ContentBlock(
            type=BlockType.HEADING,
            position=Position(page=1, index=5),
            text="REVISION HISTORY VZ_REQ_FOO_1234",
            level=1,
            style="Heading 1",
            font_info=FontInfo(size=14.0, bold=True),
            runs=[
                TextRun(text="REVISION HISTORY", struck=False),
                TextRun(text=" ", struck=False),
                TextRun(text="VZ_REQ_FOO_1234", struck=False),
            ],
        )
        revhist_table = _table(
            6, headers=["Rev.", "Author", "Description of Changes", "Date"],
            rows=[["1.0", "Author", "Initial", "2026-01-01"]],
        )
        blocks = [
            ContentBlock(  # toc entry so style-driven path is active
                type=BlockType.PARAGRAPH,
                position=Position(page=1, index=0),
                text="1\tSection One VZ_REQ_FOO_5\t5",
                style="toc 1",
                font_info=FontInfo(size=10.0),
            ),
            revhist_label,
            revhist_table,
            _heading_block(3, 1, "Section One ", "VZ_REQ_FOO_5"),
            _para(4, "body"),
        ]
        tree = GenericStructuralParser(_docx_profile()).parse(_doc(blocks))
        s = tree.parse_summary
        assert s is not None
        assert s.revhist_sections == 1
        assert s.revhist_match is not None
        assert s.revhist_match.matched_text == "REVISION HISTORY"
        assert s.revhist_match.label_block_index == 1  # post-renumber
        assert "Rev." in s.revhist_match.table_headers
        assert "Date" in s.revhist_match.table_headers

    def test_no_revhist_recorded_when_pattern_missed(self):
        # No revhist label anywhere — just a body section.
        blocks = [
            _heading_block(0, 1, "Section One ", "VZ_REQ_FOO_5"),
            _para(1, "body"),
        ]
        tree = GenericStructuralParser(_docx_profile()).parse(_doc(blocks))
        s = tree.parse_summary
        assert s.revhist_sections == 0
        assert s.revhist_match is None


class TestGlossaryEvidence:
    def test_glossary_match_captures_heading_and_table_headers(self):
        glossary_table = _table(
            2,
            headers=["Acronym/ Term", "Definition"],
            rows=[["APN", "Access Point Name"], ["IMS", "IP Multimedia Subsystem"]],
        )
        glossary_section = _heading_block(
            1, 1, "Glossary/Definitions/Acronyms ", "VZ_REQ_FOO_99"
        )
        blocks = [
            _heading_block(0, 1, "Section One ", "VZ_REQ_FOO_5"),
            glossary_section,
            glossary_table,
            _para(3, "body"),
        ]
        # embed_glossary=True so the section stays in the tree.
        profile = _docx_profile()
        tree = GenericStructuralParser(profile).parse(_doc(blocks))
        s = tree.parse_summary
        assert s.glossary_sections == 1
        assert s.glossary_match is not None
        assert "Glossary" in s.glossary_match.matched_heading
        assert "Definition" in s.glossary_match.table_headers
        assert s.glossary_match.entries_extracted == 2

    def test_glossary_evidence_set_even_when_embed_glossary_false(self):
        """When embed_glossary=False the section is dropped from the
        tree but the summary still records the match — the user wants
        to know glossary detection *fired*, regardless of downstream
        embed policy."""
        profile = _docx_profile()
        profile.embed_glossary = False
        glossary_table = _table(
            2, headers=["Acronym/ Term", "Definition"],
            rows=[["APN", "Access Point Name"]],
        )
        blocks = [
            _heading_block(0, 1, "Section One ", "VZ_REQ_FOO_5"),
            _heading_block(1, 1, "Glossary/Definitions/Acronyms ", "VZ_REQ_FOO_99"),
            glossary_table,
        ]
        tree = GenericStructuralParser(profile).parse(_doc(blocks))
        s = tree.parse_summary
        assert s.glossary_sections == 1
        assert s.glossary_match is not None
        assert s.glossary_match.entries_extracted == 1


class TestDocSummaryFields:
    def test_toc_entries_count_matches_indexed_blocks(self):
        blocks = [
            ContentBlock(
                type=BlockType.PARAGRAPH,
                position=Position(page=1, index=0),
                text="1\tA VZ_REQ_X_1\t5", style="toc 1",
                font_info=FontInfo(size=10.0),
            ),
            ContentBlock(
                type=BlockType.PARAGRAPH,
                position=Position(page=1, index=1),
                text="1.1\tB VZ_REQ_X_2\t6", style="toc 2",
                font_info=FontInfo(size=10.0),
            ),
            _heading_block(2, 1, "A ", "VZ_REQ_X_1"),
        ]
        tree = GenericStructuralParser(_docx_profile()).parse(_doc(blocks))
        assert tree.parse_summary.toc_entries == 2

    def test_format_errors_records_toc_pair_misses(self):
        blocks = [
            _heading_block(0, 1, "Unmatched ", "VZ_REQ_FOO_42"),  # no TOC entry
            _para(1, "body"),
        ]
        tree = GenericStructuralParser(_docx_profile()).parse(_doc(blocks))
        assert tree.parse_summary.format_errors.get("toc_pair_miss") == 1


# ---------------------------------------------------------------------------
# Corpus aggregation
# ---------------------------------------------------------------------------


class TestCorpusSummary:
    def test_aggregates_missing_counts(self):
        per_doc = [
            DocSummary(plan_name="A", revhist_sections=1, glossary_sections=1),
            DocSummary(plan_name="B", revhist_sections=0, glossary_sections=1),
            DocSummary(plan_name="C", revhist_sections=1, glossary_sections=0),
            DocSummary(plan_name="D", revhist_sections=0, glossary_sections=0),
        ]
        corpus = build_corpus_summary(per_doc, generated_at="2026-05-11T00:00:00Z")
        assert corpus.total_docs == 4
        assert corpus.docs_without_revhist == 2
        assert corpus.docs_without_glossary == 2

    def test_round_trip_serialization(self, tmp_path):
        per_doc = [
            DocSummary(
                plan_name="A",
                revhist_sections=1,
                revhist_match=RevhistMatch(
                    pattern_id="configured",
                    matched_text="REVISION HISTORY",
                    label_block_index=10,
                    table_headers=["Rev.", "Author"],
                ),
                glossary_sections=1,
                glossary_match=GlossaryMatch(
                    pattern_id="configured",
                    matched_heading="GLOSSARY",
                    table_headers=["Acronym/ Term", "Definition"],
                    entries_extracted=14,
                ),
                format_errors={"toc_pair_miss": 3},
            ),
        ]
        corpus = build_corpus_summary(per_doc, generated_at="2026-05-11T00:00:00Z")
        path = tmp_path / "parse_summary.json"
        corpus.save_json(path)
        loaded = CorpusSummary.load_json(path)
        assert loaded.total_docs == 1
        assert loaded.docs[0].plan_name == "A"
        assert loaded.docs[0].revhist_match.matched_text == "REVISION HISTORY"
        assert loaded.docs[0].glossary_match.entries_extracted == 14
        assert loaded.docs[0].format_errors == {"toc_pair_miss": 3}
