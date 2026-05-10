"""Tests for Phase 5 of the generic-rules pivot — skip glossary from RAG.

Two surfaces:

* **Parser** — when ``profile.embed_glossary`` is False, the glossary
  section + descendants are dropped from
  ``RequirementTree.requirements`` after ``definitions_map`` has been
  populated. The map persists for downstream acronym expansion.
* **Chunk builder** — when ``tree.embed_glossary`` is False, per-acronym
  glossary chunks (``_build_glossary_chunks``) are skipped. The
  per-requirement chunk loop never sees the glossary section because
  the parser already removed it.

Default behavior (``embed_glossary=True``) is preserved as a
regression guard.
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
from core.src.parser.structural_parser import (
    GenericStructuralParser,
    Requirement,
    RequirementTree,
    TableData,
)
from core.src.profiler.profile_schema import (
    BodyText,
    CrossReferencePatterns,
    DocumentProfile,
    HeaderFooter,
    HeadingDetection,
    PlanMetadata,
    RequirementIdPattern,
)
from core.src.vectorstore.chunk_builder import ChunkBuilder
from core.src.vectorstore.config import VectorStoreConfig


def _profile(*, embed_glossary: bool = True) -> DocumentProfile:
    return DocumentProfile(
        profile_name="test",
        profile_version=1,
        created_from=[],
        last_updated="2026-05-10",
        heading_detection=HeadingDetection(
            method="numbering",
            numbering_pattern=r"^(\d+(?:\.\d+)*)\s+\S",
            definitions_section_pattern=r"(?i)glossary|acronym|definition",
        ),
        requirement_id=RequirementIdPattern(
            pattern=r"VZ_REQ_[A-Z0-9_]+_\d+",
        ),
        plan_metadata=PlanMetadata(),
        document_zones=[],
        header_footer=HeaderFooter(),
        cross_reference_patterns=CrossReferencePatterns(),
        body_text=BodyText(font_size_min=11.0, font_size_max=12.0),
        embed_glossary=embed_glossary,
    )


def _para(idx: int, text: str, *, size: float = 12.0, bold: bool = False) -> ContentBlock:
    return ContentBlock(
        type=BlockType.PARAGRAPH,
        position=Position(page=1, index=idx),
        text=text,
        font_info=FontInfo(size=size, bold=bold),
    )


def _glossary_table(
    idx: int, headers: list[str], rows: list[list[str]]
) -> ContentBlock:
    return ContentBlock(
        type=BlockType.TABLE,
        position=Position(page=1, index=idx),
        headers=headers,
        rows=rows,
    )


def _doc(blocks: list[ContentBlock]) -> DocumentIR:
    for i, b in enumerate(blocks):
        b.position.index = i
    return DocumentIR(
        source_file="fixture.docx",
        source_format="docx",
        mno="MNO0",
        release="r1",
        doc_type="requirement",
        content_blocks=blocks,
    )


# ---------------------------------------------------------------------------
# Parser-side: drop glossary subtree
# ---------------------------------------------------------------------------


class TestParserDropsGlossary:
    def _blocks(self) -> list[ContentBlock]:
        return [
            _para(0, "1 Real Section", size=14.0, bold=True),
            _para(1, "body content under section 1"),
            _para(2, "2 Glossary", size=14.0, bold=True),
            _glossary_table(
                3,
                headers=["Acronym/ Term", "Definition"],
                rows=[
                    ["APN", "Access Point Name"],
                    ["IMS", "IP Multimedia Subsystem"],
                ],
            ),
        ]

    def test_default_keeps_glossary_section(self):
        """``embed_glossary=True`` (default) — glossary stays in ``requirements``."""
        tree = GenericStructuralParser(_profile()).parse(_doc(self._blocks()))
        section_nums = {r.section_number for r in tree.requirements}
        assert "2" in section_nums  # glossary kept
        assert tree.definitions_map == {
            "APN": "Access Point Name",
            "IMS": "IP Multimedia Subsystem",
        }
        assert tree.embed_glossary is True

    def test_flag_off_drops_glossary_subtree(self):
        """``embed_glossary=False`` — glossary section removed from
        ``requirements``; map still populated."""
        tree = GenericStructuralParser(
            _profile(embed_glossary=False)
        ).parse(_doc(self._blocks()))
        section_nums = {r.section_number for r in tree.requirements}
        assert "2" not in section_nums  # glossary dropped
        assert "1" in section_nums  # body content preserved
        # Map preserved for acronym expansion.
        assert tree.definitions_map == {
            "APN": "Access Point Name",
            "IMS": "IP Multimedia Subsystem",
        }
        assert tree.embed_glossary is False

    def test_flag_off_keeps_definitions_map(self):
        """The acronym-expansion path depends on ``definitions_map`` —
        dropping the glossary subtree must not zero it out."""
        tree = GenericStructuralParser(
            _profile(embed_glossary=False)
        ).parse(_doc(self._blocks()))
        assert len(tree.definitions_map) == 2


# ---------------------------------------------------------------------------
# Chunk builder: skip per-acronym glossary chunks
# ---------------------------------------------------------------------------


def _tree_dict(*, embed_glossary: bool, with_defs: bool = True) -> dict:
    """Minimal tree dict with one body req + a definitions map."""
    return {
        "mno": "MNO0",
        "release": "r1",
        "plan_id": "TESTPLAN",
        "plan_name": "Test Plan",
        "version": "1",
        "release_date": "2026-05-10",
        "embed_glossary": embed_glossary,
        "requirements": [
            {
                "req_id": "VZ_REQ_X_1",
                "section_number": "1",
                "title": "Body Section",
                "parent_req_id": "",
                "parent_section": "",
                "hierarchy_path": ["Body Section"],
                "zone_type": "",
                "priority": "",
                "applicability": [],
                "text": "The UE shall use APN for connectivity.",
                "tables": [],
                "images": [],
                "children": [],
                "cross_references": {
                    "internal": [],
                    "external_plans": [],
                    "standards": [],
                },
            },
        ],
        "definitions_map": (
            {"APN": "Access Point Name", "IMS": "IP Multimedia Subsystem"}
            if with_defs else {}
        ),
        "definitions_section_number": "",
        "reference_list_map": {},
        "reference_list_section_number": "",
        "referenced_standards_releases": {},
    }


class TestChunkBuilderSkipsGlossary:
    def test_default_emits_glossary_chunks(self):
        cb = ChunkBuilder(VectorStoreConfig())
        chunks = cb.build_chunks([_tree_dict(embed_glossary=True)])
        glossary_chunks = [c for c in chunks if c.chunk_id.startswith("glossary:")]
        assert len(glossary_chunks) == 2  # APN + IMS

    def test_flag_off_skips_glossary_chunks(self):
        cb = ChunkBuilder(VectorStoreConfig())
        chunks = cb.build_chunks([_tree_dict(embed_glossary=False)])
        glossary_chunks = [c for c in chunks if c.chunk_id.startswith("glossary:")]
        assert glossary_chunks == []
        # Body chunk still emitted.
        body_chunks = [c for c in chunks if c.chunk_id == "req:VZ_REQ_X_1"]
        assert len(body_chunks) == 1

    def test_flag_off_preserves_acronym_expansion(self):
        """Body chunks still get inline acronym expansion via
        ``definitions_map`` even when glossary chunks are skipped —
        that's the whole point of keeping the map."""
        cb = ChunkBuilder(VectorStoreConfig())
        chunks = cb.build_chunks([_tree_dict(embed_glossary=False)])
        body = next(c for c in chunks if c.chunk_id == "req:VZ_REQ_X_1")
        # APN → APN (Access Point Name) on first occurrence.
        assert "Access Point Name" in body.text
