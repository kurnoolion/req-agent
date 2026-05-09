"""Parse routes — Bootstrap (annotation harness) + Review (3-pane post-parse)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from core.src.models.document import BlockType, DocumentIR
from core.src.parser.parse_review import generate_compact_report
from core.src.web.bootstrap_schema import (
    AnnotationValidationError,
    SCHEMA_VERSION,
    validate_annotation_file,
)
from core.src.web.docx_html_render import render_docx_html

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parse-review", tags=["parse-review"])


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _parse_log_dir(config) -> Path:
    return config.env_dir_path() / "reports" / "parse_log"


def _list_docs(env_dir_path: Path) -> list[str]:
    """Return doc IDs that have at least a parse log OR an IR file."""
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

    # Best-effort section-heading annotation from RequirementTree
    if tree_path.exists():
        try:
            tree_data = json.loads(tree_path.read_text(encoding="utf-8"))
            text_to_idx: dict[str, int] = {}
            for blk in doc.content_blocks:
                if blk.type in (BlockType.HEADING, BlockType.PARAGRAPH) and blk.text:
                    key = blk.text.strip()[:100]
                    if key not in text_to_idx:
                        text_to_idx[key] = blk.position.index
            for req in tree_data.get("requirements", []):
                if not req.get("section_number"):
                    continue
                title = (req.get("title") or "").strip()
                if not title:
                    continue
                key = title[:100]
                if key in text_to_idx:
                    idx = text_to_idx[key]
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
        elif blk.type == BlockType.TABLE:
            b["headers"] = blk.headers or []
            b["rows"] = blk.rows or []
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
    from core.src.web.app import _template_response, config
    docs = _list_docs(config.env_dir_path())
    log_dir = _parse_log_dir(config)
    return _template_response(request, "parse_review/index.html", {
        "docs": docs,
        "log_dir_missing": not log_dir.is_dir() and not (config.env_dir_path() / "out" / "extract").is_dir(),
    })


@router.get("/{doc_id}/view", response_class=HTMLResponse)
async def parse_review_view(request: Request, doc_id: str):
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
    log_dir = _parse_log_dir(config)
    review_path = log_dir / f"{doc_id}_parse_review.json"
    try:
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "path": review_path.name}
    except Exception as exc:
        logger.error("Save review failed %s: %s", review_path, exc)
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Bootstrap (annotation harness) — sibling tab on the Parse page
# ---------------------------------------------------------------------------

def _annotations_dir(env_dir_path: Path) -> Path:
    return env_dir_path / "annotations"


def _annotations_path(env_dir_path: Path, doc_id: str) -> Path:
    return _annotations_dir(env_dir_path) / f"{doc_id}_annotations.json"


def _list_docx_inputs(env_dir_path: Path) -> list[dict[str, Any]]:
    """List DOCX files under <env_dir>/input/<MNO>/<RELEASE>/ available for annotation.

    Each entry reports whether the extract IR exists (required for annotation)
    and whether an annotation file already exists.
    """
    input_dir = env_dir_path / "input"
    out: list[dict[str, Any]] = []
    if not input_dir.is_dir():
        return out
    ir_dir = env_dir_path / "out" / "extract"
    ann_dir = _annotations_dir(env_dir_path)
    for path in sorted(input_dir.rglob("*.docx")):
        rel = path.relative_to(env_dir_path)
        doc_id = path.stem
        ir_exists = (ir_dir / f"{doc_id}_ir.json").exists() if ir_dir.is_dir() else False
        ann_exists = (ann_dir / f"{doc_id}_annotations.json").exists() if ann_dir.is_dir() else False
        ann_count = 0
        if ann_exists:
            try:
                data = json.loads((ann_dir / f"{doc_id}_annotations.json").read_text(encoding="utf-8"))
                ann_count = len(data.get("annotations", []))
            except Exception:
                ann_count = 0
        out.append({
            "doc_id": doc_id,
            "rel_path": str(rel),
            "ir_exists": ir_exists,
            "annotation_exists": ann_exists,
            "annotation_count": ann_count,
        })
    return out


def _resolve_docx_path(env_dir_path: Path, doc_id: str) -> Path | None:
    input_dir = env_dir_path / "input"
    if not input_dir.is_dir():
        return None
    matches = [p for p in input_dir.rglob(f"{doc_id}.docx")]
    return matches[0] if matches else None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@router.get("/bootstrap/docs")
async def bootstrap_list_docs(request: Request):
    from core.src.web.app import config
    env_dir = config.env_dir_path()
    docs = _list_docx_inputs(env_dir)
    ann_dir = _annotations_dir(env_dir)
    return {
        "docs": docs,
        "annotations_dir": str(ann_dir),
    }


@router.get("/bootstrap/{doc_id}/view", response_class=HTMLResponse)
async def bootstrap_view(request: Request, doc_id: str):
    from core.src.web.app import _template_response, config
    env_dir = config.env_dir_path()
    docx_path = _resolve_docx_path(env_dir, doc_id)
    if docx_path is None:
        return _template_response(request, "parse_review/_bootstrap_view.html", {
            "doc_id": doc_id,
            "error": f"DOCX file for {doc_id!r} not found under <env_dir>/input/.",
        })

    blocks, _log, ir_error = _build_annotated_blocks(doc_id, env_dir)
    annotation_path = _annotations_path(env_dir, doc_id)
    existing: list[dict[str, Any]] = []
    if annotation_path.exists():
        try:
            data = json.loads(annotation_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                existing = data.get("annotations", []) or []
        except Exception as exc:
            logger.warning("Failed to load annotations %s: %s", annotation_path, exc)

    try:
        docx_html = render_docx_html(docx_path)
        render_error: str | None = None
    except Exception as exc:
        logger.warning("DOCX render failed for %s: %s", docx_path, exc)
        docx_html = ""
        render_error = f"DOCX render failed: {exc}"

    return _template_response(request, "parse_review/_bootstrap_view.html", {
        "doc_id": doc_id,
        "docx_rel_path": str(docx_path.relative_to(env_dir)) if docx_path else "",
        "blocks": blocks,
        "block_count": len(blocks),
        "ir_error": ir_error,
        "docx_html": docx_html,
        "render_error": render_error,
        "annotation_path_rel": str(annotation_path.relative_to(env_dir)),
        "annotations": existing,
    })


@router.get("/bootstrap/{doc_id}/annotations")
async def bootstrap_load_annotations(request: Request, doc_id: str):
    from core.src.web.app import config
    env_dir = config.env_dir_path()
    path = _annotations_path(env_dir, doc_id)
    if not path.exists():
        docx_path = _resolve_docx_path(env_dir, doc_id)
        rel = str(docx_path.relative_to(env_dir)) if docx_path else ""
        return {
            "version": SCHEMA_VERSION,
            "doc_path": f"<env_dir>/{rel}" if rel else "",
            "annotations": [],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("annotation file is not a JSON object")
        return data
    except Exception as exc:
        logger.error("Annotation load failed %s: %s", path, exc)
        raise HTTPException(status_code=500, detail=f"load failed: {exc}")


@router.post("/bootstrap/{doc_id}/annotations")
async def bootstrap_save_annotations(request: Request, doc_id: str):
    from core.src.web.app import config
    env_dir = config.env_dir_path()
    path = _annotations_path(env_dir, doc_id)
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}")

    docx_path = _resolve_docx_path(env_dir, doc_id)
    if docx_path is not None and not body.get("doc_path"):
        body["doc_path"] = f"<env_dir>/{docx_path.relative_to(env_dir)}"

    try:
        sanitized = validate_annotation_file(body)
    except AnnotationValidationError as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "errors": exc.errors},
        )

    try:
        _atomic_write_json(path, sanitized)
    except Exception as exc:
        logger.error("Annotation save failed %s: %s", path, exc)
        raise HTTPException(status_code=500, detail=f"save failed: {exc}")

    return {
        "ok": True,
        "path": str(path.relative_to(env_dir)),
        "count": len(sanitized.get("annotations", [])),
    }


# ---------------------------------------------------------------------------
# Review (existing; below)
# ---------------------------------------------------------------------------

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
