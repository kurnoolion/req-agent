"""Apply user-driven `remove` annotations to a DocumentIR before parse [D-061].

User annotations live at ``<env_dir>/annotations/<doc_id>_annotations.json``
(produced by the Bootstrap tab on the Parse page). The vast majority of
kinds are positive examples for Cline rule derivation and have no
runtime effect on parsing — they just sit on disk as ground truth.

The exception is ``kind=remove``: it marks blocks (or table rows) the
user wants excluded from the parse + downstream pipeline. To keep the
pipeline mental model uniform, removes ride on the D-060 strike rails:
this module mutates the IR to mark the specified runs as ``struck`` and
sets ``font_info.strikethrough=True`` on the affected blocks. The
parser's existing FR-33 cascade (now extended to DOCX `BlockType.HEADING`
blocks per D-061) then drops the content exactly as if the source had
struck it.

Single entrypoint:

    apply_user_annotations(ir, annotations_path) -> int

Returns the count of removes applied (0 when the file is missing or
contains no remove kinds). Other annotation kinds are ignored here.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.src.models.document import (
    BlockType,
    ContentBlock,
    DocumentIR,
    FontInfo,
    TextRun,
)

logger = logging.getLogger(__name__)


def apply_user_annotations(ir: DocumentIR, annotations_path: Path) -> int:
    """Apply ``kind=remove`` annotations from *annotations_path* to *ir*.

    Mutates *ir* in place. Returns the number of remove annotations
    successfully applied. Missing / malformed files return 0 silently
    (a warning is logged) — annotations are an optional layer; the
    parser must work with or without them.
    """
    if not annotations_path.exists():
        return 0
    try:
        data = json.loads(annotations_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(
            "user_annotations: failed to load %s: %s", annotations_path, exc
        )
        return 0
    annotations = data.get("annotations") if isinstance(data, dict) else None
    if not isinstance(annotations, list):
        return 0

    applied = 0
    for ann in annotations:
        if not isinstance(ann, dict) or ann.get("kind") != "remove":
            continue
        region = ann.get("region")
        if not isinstance(region, dict):
            continue
        if "block_indices" in region:
            for idx in region.get("block_indices", []):
                if isinstance(idx, int) and 0 <= idx < len(ir.content_blocks):
                    _mark_block_struck(ir.content_blocks[idx])
                    applied += 1
        elif "block_index" in region and "row_range" in region:
            idx = region.get("block_index")
            rng = region.get("row_range")
            if isinstance(idx, int) and 0 <= idx < len(ir.content_blocks):
                if (
                    isinstance(rng, list)
                    and len(rng) == 2
                    and all(isinstance(x, int) and x >= 0 for x in rng)
                ):
                    _mark_rows_struck(ir.content_blocks[idx], rng[0], rng[1])
                    applied += 1
    return applied


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mark_block_struck(block: ContentBlock) -> None:
    """Mark every textful run on *block* as struck.

    Sets ``font_info.strikethrough=True`` (synthesizing a minimal
    ``FontInfo`` for tables / blocks that don't carry one) so the
    parser's FR-33 block-level cascade fires. Walks ``runs``,
    ``header_runs``, and ``row_runs`` so partial-strike consumers and
    UI rendering see uniform marks.
    """
    if block.font_info is None:
        block.font_info = FontInfo(size=0.0)
    block.font_info.strikethrough = True

    for run in block.runs:
        run.struck = True
    for cell in block.header_runs:
        for run in cell:
            run.struck = True
    for row in block.row_runs:
        for cell in row:
            for run in cell:
                run.struck = True


def _mark_rows_struck(block: ContentBlock, start: int, end: int) -> None:
    """Mark rows in [start, end] (inclusive) as fully struck.

    Initializes ``row_runs`` from ``rows`` for legacy IRs (pre-D-060)
    so the strike marks survive even on older IR JSON files.
    """
    if not block.row_runs and block.rows:
        block.row_runs = [
            [[TextRun(text=cell, struck=False)] for cell in row]
            for row in block.rows
        ]
    if not block.row_runs:
        return
    end = min(end, len(block.row_runs) - 1)
    for r_idx in range(max(start, 0), end + 1):
        for cell in block.row_runs[r_idx]:
            for run in cell:
                run.struck = True
