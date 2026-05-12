"""Load corrections from ``<env_dir>/corrections/`` and join each entry
to its source block in the IR.

The Review tab embeds ``block_idx`` in every corrections entry. We use
that for unambiguous IR lookup (page numbers alone collide for
multi-correction pages).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from core.src.models.document import BlockType, ContentBlock, DocumentIR
from core.src.profile_miner.records import EnrichedCorrection

logger = logging.getLogger(__name__)

NEIGHBOUR_WINDOW = 2
"""Number of blocks before + after the corrected block to include as
context in the LLM prompt. Two on each side is enough for a heading-
style correction (one neighbour above and below shows the surrounding
section structure) without bloating the prompt."""


def _block_text(b: ContentBlock) -> str:
    if b.type in (BlockType.HEADING, BlockType.PARAGRAPH):
        return (b.text or "").strip()
    if b.type == BlockType.TABLE:
        # Flatten the table for LLM context — headers + first 3 rows
        # is enough to disambiguate a glossary / revhist table from
        # body content without blowing out the prompt budget.
        parts: list[str] = []
        if b.headers:
            parts.append(" | ".join(b.headers))
        for row in (b.rows or [])[:3]:
            parts.append(" | ".join(str(c) for c in row))
        return "\n".join(parts)
    return ""


def _iter_corrections_files(env_dir: Path, doc_id: str | None) -> list[Path]:
    corr_dir = env_dir / "corrections"
    if not corr_dir.is_dir():
        return []
    if doc_id:
        p = corr_dir / f"{doc_id}_corrections.json"
        return [p] if p.exists() else []
    return sorted(corr_dir.glob("*_corrections.json"))


def load_corrections(
    env_dir: Path,
    doc_id: str | None = None,
) -> list[EnrichedCorrection]:
    """Load every corrections entry under ``<env_dir>/corrections/`` (or
    just one file when ``doc_id`` is given), join to IR, and return a
    flat list of ``EnrichedCorrection`` records.

    Entries that can't be joined to the IR (missing IR, stale block_idx)
    are logged and skipped rather than aborting the whole run.
    """
    out: list[EnrichedCorrection] = []
    ir_dir = env_dir / "out" / "extract"

    for corr_path in _iter_corrections_files(env_dir, doc_id):
        try:
            payload = json.loads(corr_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not read %s: %s", corr_path, exc)
            continue

        cur_doc_id = payload.get("doc_id") or corr_path.stem.replace(
            "_corrections", ""
        )
        ir_path = ir_dir / f"{cur_doc_id}_ir.json"
        if not ir_path.exists():
            logger.warning(
                "Skipping %s: IR not found at %s", corr_path.name, ir_path
            )
            continue

        try:
            doc = DocumentIR.load_json(ir_path)
        except Exception as exc:
            logger.warning("Could not load IR %s: %s", ir_path, exc)
            continue

        by_idx: dict[int, ContentBlock] = {
            b.position.index: b for b in doc.content_blocks
        }

        corrections = payload.get("corrections", {}) or {}
        for kind, group in (
            ("missed", corrections.get("missed_drops", [])),
            ("false_positive", corrections.get("false_positive_drops", [])),
        ):
            for entry in group or []:
                idx = entry.get("block_idx")
                if not isinstance(idx, int) or idx not in by_idx:
                    logger.warning(
                        "%s: entry has no matchable block_idx (%r) — skipping",
                        corr_path.name, idx,
                    )
                    continue
                block = by_idx[idx]
                neighbours = [
                    _block_text(by_idx[i])
                    for i in range(idx - NEIGHBOUR_WINDOW, idx + NEIGHBOUR_WINDOW + 1)
                    if i != idx and i in by_idx
                ]
                expected = (
                    entry.get("expected_reason")
                    or entry.get("reason")
                    or ""
                )
                out.append(EnrichedCorrection(
                    doc_id=cur_doc_id,
                    kind=kind,
                    expected_reason=expected,
                    block_idx=idx,
                    pages=str(entry.get("pages", "")),
                    block_text=_block_text(block),
                    neighbour_texts=[t for t in neighbours if t],
                    comment=entry.get("comment", "") or "",
                ))

    return out
