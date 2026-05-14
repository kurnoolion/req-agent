"""Tests for SECTION_HEADING annotations emitted by the parse-review
web route's ``_build_annotated_blocks``.

Two code paths exist:

1. **Preferred:** ``Requirement.source_block_idx`` (carried by the
   parser since the section-handling strand fix) is a direct
   index into ``content_blocks`` — used for O(1) lookup, immune to
   block-text-vs-title shape mismatches.
2. **Legacy:** when ``source_block_idx`` is absent (tree.json
   pre-dates the field), fall back to title-keyed fuzzy matching
   against the IR's block.text. Brittle — the originating bug —
   but kept for back-compat with existing tree.json files.

Both paths are exercised here.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.src.models.document import (
    BlockType,
    ContentBlock,
    DocumentIR,
    FontInfo,
    Position,
)
from core.src.web.routes.parse_review import _build_annotated_blocks


def _make_doc_with_heading_then_paragraph(env_dir: Path, doc_id: str,
                                          heading_text: str,
                                          body_text: str) -> None:
    """Write a minimal IR with one heading block + one paragraph body."""
    blocks = [
        ContentBlock(
            type=BlockType.PARAGRAPH,
            position=Position(page=1, index=0),
            text=heading_text,
            font_info=FontInfo(size=14.0, bold=True),
        ),
        ContentBlock(
            type=BlockType.PARAGRAPH,
            position=Position(page=1, index=1),
            text=body_text,
            font_info=FontInfo(size=12.0),
        ),
    ]
    ir = DocumentIR(
        source_file=f"{doc_id}.docx",
        source_format="docx",
        content_blocks=blocks,
    )
    out_dir = env_dir / "out" / "extract"
    out_dir.mkdir(parents=True, exist_ok=True)
    ir.save_json(out_dir / f"{doc_id}_ir.json")


def _write_tree(env_dir: Path, doc_id: str, requirements: list[dict]) -> None:
    """Write a minimal tree.json with the supplied requirements list."""
    tree_dir = env_dir / "out" / "parse"
    tree_dir.mkdir(parents=True, exist_ok=True)
    (tree_dir / f"{doc_id}_tree.json").write_text(
        json.dumps({"requirements": requirements}), encoding="utf-8",
    )


def _find_section_heading_annotation(
    blocks: list[dict], block_idx: int,
) -> dict | None:
    for b in blocks:
        if b["idx"] != block_idx:
            continue
        for a in b.get("annotations", []):
            if a.get("type") == "section_heading":
                return a
    return None


# ---------------------------------------------------------------------------
# Preferred path: source_block_idx
# ---------------------------------------------------------------------------

def test_section_annotation_via_source_block_idx(tmp_path: Path):
    """Heading text differs from req.title (numbering + req_id stripped
    during classification); the title-keyed lookup would miss but
    source_block_idx is a direct index. Annotation must still attach
    to block_idx=0."""
    doc_id = "DOC1"
    _make_doc_with_heading_then_paragraph(
        tmp_path, doc_id,
        heading_text="1.2.3.4 Important Section VZ_REQ_fooBar_12345",
        body_text="Section body content.",
    )
    _write_tree(tmp_path, doc_id, requirements=[{
        "section_number": "1.2.3.4",
        "title": "Important Section",   # post-stripping form
        "req_id": "VZ_REQ_fooBar_12345",
        "source_block_idx": 0,          # direct index
    }])

    blocks, _, err = _build_annotated_blocks(doc_id, tmp_path)
    assert err is None
    ann = _find_section_heading_annotation(blocks, block_idx=0)
    assert ann is not None
    assert ann["section_number"] == "1.2.3.4"
    assert ann["req_id"] == "VZ_REQ_fooBar_12345"


def test_section_annotation_skips_when_source_block_idx_out_of_range(
    tmp_path: Path,
):
    """Stale tree.json paired with a refreshed IR: source_block_idx
    points outside the current doc's blocks. Skip silently — don't
    crash, don't fall through to title-fuzzy-match."""
    doc_id = "DOC2"
    _make_doc_with_heading_then_paragraph(
        tmp_path, doc_id,
        heading_text="1 Foo",
        body_text="body",
    )
    _write_tree(tmp_path, doc_id, requirements=[{
        "section_number": "1",
        "title": "Foo",
        "source_block_idx": 999,   # outside the doc
    }])

    blocks, _, err = _build_annotated_blocks(doc_id, tmp_path)
    assert err is None
    assert _find_section_heading_annotation(blocks, 0) is None
    assert _find_section_heading_annotation(blocks, 1) is None


# ---------------------------------------------------------------------------
# Legacy path: title-keyed fallback when source_block_idx is absent
# ---------------------------------------------------------------------------

def test_section_annotation_falls_back_to_title_match_for_legacy_tree(
    tmp_path: Path,
):
    """Legacy tree.json without source_block_idx still works for the
    common case where the block's full text equals req.title (PDF
    extractor / numbering-pattern method)."""
    doc_id = "DOC3"
    _make_doc_with_heading_then_paragraph(
        tmp_path, doc_id,
        heading_text="1 Foo",   # block text matches req.title exactly
        body_text="body",
    )
    _write_tree(tmp_path, doc_id, requirements=[{
        "section_number": "1",
        "title": "1 Foo",       # legacy: title-as-full-text
        # source_block_idx intentionally omitted
    }])

    blocks, _, err = _build_annotated_blocks(doc_id, tmp_path)
    assert err is None
    ann = _find_section_heading_annotation(blocks, block_idx=0)
    assert ann is not None


def test_section_annotation_legacy_fallback_misses_on_title_shape_mismatch(
    tmp_path: Path,
):
    """The originating-bug case: legacy tree.json (no source_block_idx),
    block text has numbering + req_id appended, req.title is the
    stripped form. Fallback path's title-keyed lookup misses. This is
    documented historical behavior — the preferred path (test above)
    is the fix; this test pins the legacy behavior so any future
    fallback-tightening is a deliberate choice."""
    doc_id = "DOC4"
    _make_doc_with_heading_then_paragraph(
        tmp_path, doc_id,
        heading_text="1.2.3.4 Foo VZ_REQ_fooBar_12345",
        body_text="body",
    )
    _write_tree(tmp_path, doc_id, requirements=[{
        "section_number": "1.2.3.4",
        "title": "Foo",
        # source_block_idx intentionally omitted → triggers legacy fallback
    }])

    blocks, _, err = _build_annotated_blocks(doc_id, tmp_path)
    assert err is None
    assert _find_section_heading_annotation(blocks, 0) is None
