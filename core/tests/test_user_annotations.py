"""Tests for user-driven `remove` annotations [D-061].

Covers ``apply_user_annotations(ir, path)`` — the IR-mutation pre-pass
that translates user `remove` annotations into D-060 strike marks so
the parser drops them via the existing FR-33 cascade.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.src.models.document import (
    BlockType,
    ContentBlock,
    DocumentIR,
    FontInfo,
    Position,
    TextRun,
)
from core.src.parser.user_annotations import apply_user_annotations


def _write(path: Path, annotations: list[dict]) -> Path:
    path.write_text(
        json.dumps({
            "version": 1,
            "doc_path": "test.docx",
            "annotations": annotations,
        }),
        encoding="utf-8",
    )
    return path


def _para(idx: int, text: str) -> ContentBlock:
    return ContentBlock(
        type=BlockType.PARAGRAPH,
        position=Position(page=1, index=idx),
        text=text,
        runs=[TextRun(text=text, struck=False)],
        font_info=FontInfo(size=11.0, strikethrough=False),
    )


def _heading(idx: int, text: str, level: int) -> ContentBlock:
    return ContentBlock(
        type=BlockType.HEADING,
        position=Position(page=1, index=idx),
        text=text,
        level=level,
        runs=[TextRun(text=text, struck=False)],
        font_info=FontInfo(size=18.0, strikethrough=False),
    )


def _table(idx: int) -> ContentBlock:
    return ContentBlock(
        type=BlockType.TABLE,
        position=Position(page=1, index=idx),
        headers=["Code", "Action"],
        rows=[["22", "exp"], ["23", "stop"], ["24", "linear"]],
        header_runs=[[TextRun("Code")], [TextRun("Action")]],
        row_runs=[
            [[TextRun("22")], [TextRun("exp")]],
            [[TextRun("23")], [TextRun("stop")]],
            [[TextRun("24")], [TextRun("linear")]],
        ],
    )


# ---------------------------------------------------------------------------
# apply_user_annotations
# ---------------------------------------------------------------------------

class TestApplyRemoveAnnotations:
    def test_missing_file_returns_zero_silently(self, tmp_path: Path):
        ir = DocumentIR(source_file="t.docx", source_format="docx",
                        content_blocks=[_para(0, "x")])
        n = apply_user_annotations(ir, tmp_path / "no_such.json")
        assert n == 0
        assert ir.content_blocks[0].font_info.strikethrough is False

    def test_block_indices_marks_blocks_struck(self, tmp_path: Path):
        ir = DocumentIR(
            source_file="t.docx", source_format="docx",
            content_blocks=[_para(0, "keep"), _para(1, "remove me"),
                            _para(2, "keep too")],
        )
        path = _write(tmp_path / "ann.json", [
            {"id": "ann_001", "kind": "remove",
             "region": {"block_indices": [1]}},
        ])
        n = apply_user_annotations(ir, path)
        assert n == 1
        assert ir.content_blocks[0].font_info.strikethrough is False
        assert ir.content_blocks[1].font_info.strikethrough is True
        assert all(r.struck for r in ir.content_blocks[1].runs)
        assert ir.content_blocks[2].font_info.strikethrough is False

    def test_block_indices_multi_block_range(self, tmp_path: Path):
        ir = DocumentIR(
            source_file="t.docx", source_format="docx",
            content_blocks=[_para(i, f"p{i}") for i in range(5)],
        )
        path = _write(tmp_path / "ann.json", [
            {"id": "ann_001", "kind": "remove",
             "region": {"block_indices": [1, 2, 3]}},
        ])
        n = apply_user_annotations(ir, path)
        assert n == 3
        struck = [b.font_info.strikethrough for b in ir.content_blocks]
        assert struck == [False, True, True, True, False]

    def test_row_range_marks_table_rows(self, tmp_path: Path):
        ir = DocumentIR(
            source_file="t.docx", source_format="docx",
            content_blocks=[_table(0)],
        )
        path = _write(tmp_path / "ann.json", [
            {"id": "ann_001", "kind": "remove",
             "region": {"block_index": 0, "row_range": [1, 2]}},
        ])
        n = apply_user_annotations(ir, path)
        assert n == 1
        block = ir.content_blocks[0]
        # Row 0 untouched; rows 1-2 fully struck
        assert not block.row_all_struck(0)
        assert block.row_all_struck(1)
        assert block.row_all_struck(2)
        # Whole-table strikethrough is NOT set — the parser drops only
        # the marked rows; header + row 0 remain.
        assert block.font_info is None or not block.font_info.strikethrough

    def test_remove_table_block_marks_every_run(self, tmp_path: Path):
        ir = DocumentIR(
            source_file="t.docx", source_format="docx",
            content_blocks=[_table(0)],
        )
        path = _write(tmp_path / "ann.json", [
            {"id": "ann_001", "kind": "remove",
             "region": {"block_indices": [0]}},
        ])
        apply_user_annotations(ir, path)
        block = ir.content_blocks[0]
        assert block.font_info.strikethrough is True
        assert block.header_all_struck()
        for i in range(len(block.row_runs)):
            assert block.row_all_struck(i)

    def test_other_kinds_ignored(self, tmp_path: Path):
        # toc / strikethrough / etc annotations don't mutate the IR via
        # this path — they're either auto-detected at extract time or
        # used only for ground-truth.
        ir = DocumentIR(
            source_file="t.docx", source_format="docx",
            content_blocks=[_para(0, "x"), _para(1, "y")],
        )
        path = _write(tmp_path / "ann.json", [
            {"id": "ann_001", "kind": "toc",
             "region": {"block_indices": [0, 1]}},
            {"id": "ann_002", "kind": "strikethrough",
             "region": {"block_indices": [0]}},
        ])
        n = apply_user_annotations(ir, path)
        assert n == 0
        for b in ir.content_blocks:
            assert b.font_info.strikethrough is False

    def test_out_of_bounds_index_skipped(self, tmp_path: Path):
        ir = DocumentIR(
            source_file="t.docx", source_format="docx",
            content_blocks=[_para(0, "x")],
        )
        path = _write(tmp_path / "ann.json", [
            {"id": "ann_001", "kind": "remove",
             "region": {"block_indices": [99]}},
        ])
        n = apply_user_annotations(ir, path)
        assert n == 0
        assert ir.content_blocks[0].font_info.strikethrough is False

    def test_malformed_json_returns_zero(self, tmp_path: Path):
        path = tmp_path / "ann.json"
        path.write_text("{ this is not valid json", encoding="utf-8")
        ir = DocumentIR(source_file="t.docx", source_format="docx",
                        content_blocks=[_para(0, "x")])
        n = apply_user_annotations(ir, path)
        assert n == 0


# ---------------------------------------------------------------------------
# Parser-after-apply: cascade fires for remove on a heading
# ---------------------------------------------------------------------------

class TestParserAfterRemove:
    """Once apply_user_annotations marks a heading struck, the parser's
    FR-33 cascade drops the section. Validates the end-to-end remove
    flow through the existing strike rails."""

    def _parse(self, ir: DocumentIR):
        from core.src.profiler.profile_schema import (
            DocumentProfile,
            HeadingDetection,
            RequirementIdPattern,
        )
        from core.src.parser.structural_parser import GenericStructuralParser

        profile = DocumentProfile(
            profile_name="test",
            heading_detection=HeadingDetection(),
            requirement_id=RequirementIdPattern(pattern="VZ_REQ_[A-Z0-9_]+"),
        )
        return GenericStructuralParser(profile).parse(ir)

    def test_remove_section_via_heading_cascades(self, tmp_path: Path):
        ir = DocumentIR(
            source_file="t.docx", source_format="docx",
            content_blocks=[
                _heading(0, "Test Plan Mapping", level=1),
                _para(1, "Body of test-plan-mapping section."),
                _para(2, "More body content."),
                _heading(3, "Live Section", level=1),
                _para(4, "Live body content."),
            ],
        )
        path = _write(tmp_path / "ann.json", [
            {"id": "ann_001", "kind": "remove",
             "region": {"block_indices": [0]}},
        ])
        apply_user_annotations(ir, path)
        tree = self._parse(ir)
        # Heading marked struck → cascade fires through subsequent
        # body until next sibling heading. cascade_blocks_dropped > 0.
        assert tree.parse_stats.cascade_blocks_dropped >= 2
