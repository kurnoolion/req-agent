"""Parse routes — Summary landing + per-doc Review.

Two surfaces, both server-rendered (no client-side state):
  * ``GET /parse-review/`` — Summary table over the parsed corpus.
    Each Doc cell links to its Review page.
  * ``GET /parse-review/<doc_id>`` — per-doc Review (3-pane annotated
    view) with a Back link to Summary.

The legacy Bootstrap (annotation harness) tab was deleted on
2026-05-15 — superseded by the profile_miner CLI loop. See D-079..D-081
context in DECISIONS.md and STATUS.md.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from core.src.models.document import BlockType, DocumentIR
from core.src.parser.parse_review import generate_compact_report

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parse-review", tags=["parse-review"])


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _parse_log_dir(config) -> Path:
    return config.env_dir_path() / "reports" / "parse_log"


def _list_docs(env_dir_path: Path) -> list[str]:
    """Return doc IDs that have at least a parse log OR an IR file.

    Retained for diagnostic / test use; the Summary landing reads
    docs from ``parse_summary.json`` and per-doc Review accepts any
    ``<doc_id>`` whose IR or parse_log exists.
    """
    log_dir = env_dir_path / "reports" / "parse_log"
    ir_dir = env_dir_path / "out" / "extract"
    ids: set[str] = set()
    if log_dir.is_dir():
        for p in log_dir.glob("*_parse_log.json"):
            ids.add(p.stem.replace("_parse_log", ""))
    if ir_dir.is_dir():
        for p in ir_dir.glob("*_ir.json"):
            ids.add(p.stem.replace("_ir", ""))
    return sorted(ids)


def _load_log(env_dir_path: Path, doc_id: str) -> dict[str, Any]:
    p = env_dir_path / "reports" / "parse_log" / f"{doc_id}_parse_log.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load parse log %s: %s", p, exc)
    return {}


def _load_or_default_review(log_dir: Path, doc_id: str) -> dict[str, Any]:
    review_path = log_dir / f"{doc_id}_parse_review.json"
    if review_path.exists():
        try:
            return json.loads(review_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load parse review %s: %s", review_path, exc)
    return {
        "doc_id": doc_id,
        "reviewer": "",
        "review_date": str(date.today()),
        "overall_verdict": "",
        "corrections": {
            "false_positive_drops": [],
            "missed_drops": [],
            "toc_error": None,
            "revhist_error": None,
            "glossary_error": None,
            "acronym_wrong_expansion": [],
            "acronym_missed": [],
            "acronym_extra": [],
        },
        "notes": "",
    }


# ---------------------------------------------------------------------------
# Block assembly
# ---------------------------------------------------------------------------

def _build_annotated_blocks(
    doc_id: str,
    env_dir_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    """Load DocumentIR + ParseLog and return (blocks, log, error_message).

    Each block dict has an `annotations` list with parser-derived labels.
    Returns an error string (not exception) if the IR is missing.
    """
    ir_path = env_dir_path / "out" / "extract" / f"{doc_id}_ir.json"
    log_path = env_dir_path / "reports" / "parse_log" / f"{doc_id}_parse_log.json"
    tree_path = env_dir_path / "out" / "parse" / f"{doc_id}_tree.json"

    if not ir_path.exists():
        return [], {}, f"DocumentIR not found ({ir_path.name}). Run the extract stage first."

    doc = DocumentIR.load_json(ir_path)

    log: dict[str, Any] = {}
    if log_path.exists():
        try:
            log = json.loads(log_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Parse log load error %s: %s", log_path, exc)

    # --- annotation index: block_idx -> list[dict] ---
    ann: dict[int, list[dict[str, Any]]] = {}

    _reason_to_type = {
        "toc": "dropped_toc",
        "revhist": "dropped_revhist",
        "text_strikethrough": "dropped_struck",
        "cascade": "dropped_cascade",
    }
    for r in log.get("dropped_blocks", []):
        ann_type = _reason_to_type.get(r["reason"], f"dropped_{r['reason']}")
        for idx in range(r["block_start"], r["block_end"] + 1):
            ann.setdefault(idx, []).append({"type": ann_type, "reason": r["reason"]})

    gs = log.get("glossary_section")
    if gs:
        for idx in range(gs["block_start"], gs["block_end"] + 1):
            if idx not in ann:
                ann.setdefault(idx, []).append({
                    "type": "glossary",
                    "section_number": gs.get("section_number", ""),
                    "section_title": gs.get("section_title", ""),
                })

    # Section-heading annotations from RequirementTree.
    # Preferred path: ``Requirement.source_block_idx`` (carried since the
    # parser-side fix) lets us do an O(1) idx lookup, immune to title
    # vs. block-text shape mismatches. Legacy tree.json from before the
    # field was added falls back to the previous title-keyed fuzzy match.
    if tree_path.exists():
        try:
            tree_data = json.loads(tree_path.read_text(encoding="utf-8"))
            doc_block_idxs = {b.position.index for b in doc.content_blocks}
            text_to_idx: dict[str, int] | None = None  # built lazily for fallback
            for req in tree_data.get("requirements", []):
                if not req.get("section_number"):
                    continue
                idx = req.get("source_block_idx")
                if idx is None:
                    # Legacy tree.json without source_block_idx — fall
                    # back to title-keyed lookup. Build the map once.
                    if text_to_idx is None:
                        text_to_idx = {}
                        for blk in doc.content_blocks:
                            if blk.type in (BlockType.HEADING, BlockType.PARAGRAPH) and blk.text:
                                key = blk.text.strip()[:100]
                                if key not in text_to_idx:
                                    text_to_idx[key] = blk.position.index
                    title = (req.get("title") or "").strip()
                    if not title:
                        continue
                    idx = text_to_idx.get(title[:100])
                    if idx is None:
                        continue
                elif idx not in doc_block_idxs:
                    # source_block_idx points outside this doc — guard
                    # against stale tree.json paired with a refreshed IR.
                    continue
                if idx not in ann:
                    ann.setdefault(idx, []).append({
                        "type": "section_heading",
                        "section_number": req.get("section_number", ""),
                        "req_id": req.get("req_id") or "",
                    })
        except Exception:
            pass

    # --- build flat block list ---
    blocks: list[dict[str, Any]] = []
    for blk in doc.content_blocks:
        idx = blk.position.index
        b: dict[str, Any] = {
            "idx": idx,
            "page": blk.position.page,
            "type": blk.type.value,
            "annotations": ann.get(idx, []),
        }
        if blk.type in (BlockType.HEADING, BlockType.PARAGRAPH):
            b["text"] = blk.text or ""
            b["level"] = blk.level
            fi = blk.font_info
            b["bold"] = fi.bold if fi else False
            b["italic"] = fi.italic if fi else False
            b["all_caps"] = fi.all_caps if fi else False
            b["strikethrough"] = fi.strikethrough if fi else False
            b["font_size"] = fi.size if fi else None
            # D-060: per-run strike state for span-level rendering. Empty
            # for legacy IRs; template falls back to whole-block strike.
            b["runs"] = [
                {"text": r.text, "struck": r.struck} for r in blk.runs
            ]
        elif blk.type == BlockType.TABLE:
            b["headers"] = blk.headers or []
            b["rows"] = blk.rows or []
            # D-060: per-cell run lists for table strike rendering. Each
            # cell is a list of {text, struck} dicts. row_struck[i] tells
            # the template which whole rows are struck so they can be
            # styled accordingly.
            b["header_runs"] = [
                [{"text": r.text, "struck": r.struck} for r in cell]
                for cell in blk.header_runs
            ]
            b["row_runs"] = [
                [
                    [{"text": r.text, "struck": r.struck} for r in cell]
                    for cell in row
                ]
                for row in blk.row_runs
            ]
            b["row_struck"] = [
                blk.row_all_struck(i) for i in range(len(blk.row_runs))
            ]
            b["header_struck"] = blk.header_all_struck()
            fi = blk.font_info
            b["table_struck"] = fi.strikethrough if fi else False
        elif blk.type == BlockType.IMAGE:
            b["image_path"] = blk.image_path or ""
            b["surrounding_text"] = blk.surrounding_text or ""
        blocks.append(b)

    return blocks, log, None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
async def parse_review_index(request: Request):
    """Summary landing — corpus-level rollup of profile-driven detection
    evidence with one row per parsed doc. Each Doc cell links to its
    per-doc Review page. Sourced from
    ``<env_dir>/reports/parse_summary.json``, written by the parse
    stage.
    """
    from core.src.web.app import _template_response, config
    from core.src.parser.parse_summary import CorpusSummary

    summary_path = config.env_dir_path() / "reports" / "parse_summary.json"
    corpus = None
    error = None
    if not summary_path.exists():
        error = (
            f"No parse_summary.json at {summary_path}. Run the parse stage "
            "(this artifact is emitted at the end of every parse run)."
        )
    else:
        try:
            corpus = CorpusSummary.load_json(summary_path)
        except Exception as exc:
            error = f"Could not load parse_summary.json: {exc}"

    return _template_response(request, "parse_review/index.html", {
        "corpus": corpus,
        "error": error,
        "summary_path": str(summary_path),
    })


@router.get("/{doc_id}", response_class=HTMLResponse)
async def parse_review_view(request: Request, doc_id: str):
    """Per-doc Review page — 3-pane annotated view. Reached by clicking
    a Doc cell on the Summary landing. Includes a Back link to the
    Summary route.
    """
    from core.src.web.app import _template_response, config
    env_dir = config.env_dir_path()
    blocks, log, error = _build_annotated_blocks(doc_id, env_dir)
    review = _load_or_default_review(_parse_log_dir(config), doc_id)
    annotated_count = sum(1 for b in blocks if b.get("annotations"))
    return _template_response(request, "parse_review/_view.html", {
        "doc_id": doc_id,
        "blocks": blocks,
        "log": log,
        "review": review,
        "error": error,
        "block_count": len(blocks),
        "annotated_count": annotated_count,
    })


@router.post("/{doc_id}/save")
async def parse_review_save(request: Request, doc_id: str):
    from core.src.web.app import config
    body = await request.json()
    env_dir = config.env_dir_path()
    log_dir = _parse_log_dir(config)
    review_path = log_dir / f"{doc_id}_parse_review.json"
    corrections_path = env_dir / "corrections" / f"{doc_id}_corrections.json"
    try:
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
        # Also emit a corrections-only artifact for the Phase 3 regex-mining CLI.
        corrections_payload = {
            "doc_id": body.get("doc_id", doc_id),
            "reviewer": body.get("reviewer", ""),
            "review_date": body.get("review_date", ""),
            "corrections": body.get("corrections", {}),
        }
        corrections_path.parent.mkdir(parents=True, exist_ok=True)
        corrections_path.write_text(
            json.dumps(corrections_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return {
            "ok": True,
            "review_path": str(review_path.relative_to(env_dir)),
            "corrections_path": str(corrections_path.relative_to(env_dir)),
        }
    except Exception as exc:
        logger.error("Save review failed %s: %s", review_path, exc)
        return {"ok": False, "error": str(exc)}


@router.post("/{doc_id}/report", response_class=HTMLResponse)
async def parse_review_report(request: Request, doc_id: str):
    from core.src.web.app import _template_response, config
    body = await request.json()
    log_dir = _parse_log_dir(config)
    review_path = log_dir / f"{doc_id}_parse_review.json"
    try:
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        return _template_response(request, "parse_review/_report.html", {
            "report": f"Save failed: {exc}",
        })
    log_path = log_dir / f"{doc_id}_parse_log.json"
    try:
        report = generate_compact_report(
            review_path,
            log_path=log_path if log_path.exists() else None,
        )
    except Exception as exc:
        report = f"Report generation failed: {exc}"
    return _template_response(request, "parse_review/_report.html", {"report": report})
