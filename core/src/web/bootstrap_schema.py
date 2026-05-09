"""Validation for bootstrap annotation files.

The annotation harness writes a JSON file at
``<env_dir>/annotations/<plan>_annotations.json`` shaped per
``cline-playbooks/annotation-schema.md``. This module enforces the schema
on save: every entry's ``kind`` is in the supported set; ``region`` matches
one of two shapes (flat ``block_indices`` for paragraph/heading/whole-table
annotations, or ``block_index`` + ``row_range`` for row-precise table
annotations); kind-specific optional fields use allowed enum values; ``id``
values are unique within the file; ``notes`` stays under 30 chars.

References split into three top-level kinds: ``reference_intra_doc`` (same
doc), ``reference_cross_doc`` (other plan/MNO), ``reference_spec`` (public
standard). Spec citations carry a required ``style`` field (``direct`` for
inline ``3GPP TS X.Y §Z`` shape; ``indirect`` for bracketed citations like
``[5]`` that resolve via the doc's references list). Two supporting kinds
mirror the definitions/glossary pattern: ``reference_list`` marks the
bibliography section; ``reference_list_entry`` marks individual numbered
entries (optional ground truth for resolver eval).

Each reference kind accepts an optional ``target`` dict with kind-specific
allowed keys; unknown keys are silently stripped. Target is purely
informational for rule derivation — it becomes resolver-eval ground truth.

Validation returns the sanitized payload (extra unknown fields stripped per
kind) or raises :class:`AnnotationValidationError` listing every issue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

NOTES_MAX_CHARS = 30
SCHEMA_VERSION = 1

KINDS: tuple[str, ...] = (
    "section_heading",
    "req_id",
    "toc",
    "strikethrough",
    "version_history",
    "definitions",
    "applicability",
    "priority",
    "reference_intra_doc",
    "reference_cross_doc",
    "reference_spec",
    "reference_list",
    "reference_list_entry",
)

SPEC_REFERENCE_STYLES: tuple[str, ...] = ("direct", "indirect")
REFERENCE_LIST_NUMBERING_STYLES: tuple[str, ...] = (
    "bracketed",
    "plain",
    "parenthesized",
)
REFERENCE_LIST_LAYOUTS: tuple[str, ...] = (
    "paragraph_list",
    "two_col_table",
    "three_col_table",
)
STRIKETHROUGH_SUBKINDS: tuple[str, ...] = (
    "full_paragraph",
    "table_row",
    "partial_cell",
    "section_heading",
)
STRIKETHROUGH_VISUALS: tuple[str, ...] = ("line", "font_flag", "both")
TOC_PATTERN_HINTS: tuple[str, ...] = (
    "leader-dot-page",
    "indented-leveled",
    "plain-list",
)
DEFINITIONS_LAYOUTS: tuple[str, ...] = (
    "paragraph_list",
    "two_col_table",
    "three_col_table",
    "inline_glossary",
)
REQ_ID_PLACEMENTS: tuple[str, ...] = ("leading", "trailing")
APPLICABILITY_POSITIONS: tuple[str, ...] = (
    "after_heading",
    "inline_in_para",
    "separate_block",
)
VERSION_HISTORY_SUBTYPES: tuple[str, ...] = ("heading_only", "full_block")

# Per-kind allowed keys for the optional `target` dict. Type is the JSON
# scalar type (`str` or `int`); unknown keys are silently stripped on save.
TARGET_KEYS_BY_KIND: dict[str, dict[str, type]] = {
    "reference_intra_doc": {"section_number": str, "req_id": str},
    "reference_cross_doc": {"plan_id": str, "section_number": str, "req_id": str},
    "reference_spec": {"spec": str, "section": str, "ref_number": int},
    "reference_list_entry": {"spec": str, "section": str},
}


class AnnotationValidationError(ValueError):
    """Raised when an annotation payload fails schema validation."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors) or "validation failed")
        self.errors = list(errors)


@dataclass
class _Ctx:
    errors: list[str] = field(default_factory=list)

    def err(self, msg: str) -> None:
        self.errors.append(msg)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def validate_annotation_file(payload: Any) -> dict[str, Any]:
    """Validate a full annotation-file payload and return the sanitized form.

    Raises :class:`AnnotationValidationError` if any check fails. The returned
    dict is suitable to write to disk verbatim.
    """
    ctx = _Ctx()
    if not isinstance(payload, dict):
        raise AnnotationValidationError(["payload must be a JSON object"])

    version = payload.get("version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        ctx.err(f"unsupported version {version!r}; expected {SCHEMA_VERSION}")

    doc_path = payload.get("doc_path")
    if not isinstance(doc_path, str) or not doc_path:
        ctx.err("doc_path must be a non-empty string")

    raw_anns = payload.get("annotations")
    if not isinstance(raw_anns, list):
        ctx.err("annotations must be an array")
        raw_anns = []

    seen_ids: set[str] = set()
    sanitized: list[dict[str, Any]] = []
    for i, ann in enumerate(raw_anns):
        if not isinstance(ann, dict):
            ctx.err(f"annotations[{i}] must be an object")
            continue
        ok = _validate_annotation(ann, i, seen_ids, ctx)
        if ok is not None:
            sanitized.append(ok)

    if ctx.errors:
        raise AnnotationValidationError(ctx.errors)

    return {
        "version": SCHEMA_VERSION,
        "doc_path": doc_path,
        "annotations": sanitized,
    }


# ---------------------------------------------------------------------------
# Per-annotation validation
# ---------------------------------------------------------------------------

def _validate_annotation(
    ann: dict[str, Any], idx: int, seen_ids: set[str], ctx: _Ctx
) -> dict[str, Any] | None:
    prefix = f"annotations[{idx}]"

    ann_id = ann.get("id")
    if not isinstance(ann_id, str) or not ann_id:
        ctx.err(f"{prefix}.id must be a non-empty string")
        ann_id = None
    elif ann_id in seen_ids:
        ctx.err(f"{prefix}.id duplicate: {ann_id!r}")
    else:
        seen_ids.add(ann_id)

    kind = ann.get("kind")
    if kind not in KINDS:
        ctx.err(f"{prefix}.kind must be one of {KINDS}; got {kind!r}")
        return None

    region = ann.get("region")
    region_clean = _validate_region(region, prefix, ctx)
    if region_clean is None:
        return None

    notes = ann.get("notes", "")
    if notes is None:
        notes = ""
    if not isinstance(notes, str):
        ctx.err(f"{prefix}.notes must be a string")
        notes = ""
    elif len(notes) > NOTES_MAX_CHARS:
        ctx.err(
            f"{prefix}.notes exceeds {NOTES_MAX_CHARS} chars "
            f"(got {len(notes)})"
        )

    out: dict[str, Any] = {
        "id": ann_id or f"ann_{idx:03d}",
        "kind": kind,
        "region": region_clean,
    }
    if notes:
        out["notes"] = notes

    _apply_kind_fields(kind, ann, out, prefix, ctx)
    return out


def _validate_region(
    region: Any, prefix: str, ctx: _Ctx
) -> dict[str, Any] | None:
    if not isinstance(region, dict):
        ctx.err(f"{prefix}.region must be an object")
        return None

    if "block_indices" in region:
        bi = region["block_indices"]
        if (
            not isinstance(bi, list)
            or not bi
            or not all(isinstance(x, int) and x >= 0 for x in bi)
        ):
            ctx.err(
                f"{prefix}.region.block_indices must be a non-empty array of "
                f"non-negative integers"
            )
            return None
        return {"block_indices": list(bi)}

    if "block_index" in region:
        b = region["block_index"]
        if not isinstance(b, int) or b < 0:
            ctx.err(f"{prefix}.region.block_index must be a non-negative int")
            return None
        rr = region.get("row_range")
        if rr is None:
            return {"block_index": b}
        if (
            not isinstance(rr, list)
            or len(rr) != 2
            or not all(isinstance(x, int) and x >= 0 for x in rr)
            or rr[0] > rr[1]
        ):
            ctx.err(
                f"{prefix}.region.row_range must be [start, end] with "
                f"0 <= start <= end"
            )
            return None
        return {"block_index": b, "row_range": [rr[0], rr[1]]}

    ctx.err(
        f"{prefix}.region must have either 'block_indices' or "
        f"'block_index' (with optional 'row_range')"
    )
    return None


def _apply_kind_fields(
    kind: str,
    ann: dict[str, Any],
    out: dict[str, Any],
    prefix: str,
    ctx: _Ctx,
) -> None:
    """Copy kind-specific optional fields from *ann* to *out* with validation."""
    if kind == "section_heading":
        _opt_int(ann, out, "depth", prefix, ctx, lo=1, hi=9)
        _opt_str(ann, out, "section_number", prefix, ctx)
        _opt_bool(ann, out, "is_numbered", prefix, ctx)
        _opt_int(ann, out, "title_char_count", prefix, ctx, lo=0)

    elif kind == "req_id":
        _opt_enum(ann, out, "placement", REQ_ID_PLACEMENTS, prefix, ctx)
        _opt_str(ann, out, "format_hint", prefix, ctx)

    elif kind == "toc":
        _opt_enum(ann, out, "pattern_hint", TOC_PATTERN_HINTS, prefix, ctx)

    elif kind == "strikethrough":
        _opt_enum(ann, out, "subkind", STRIKETHROUGH_SUBKINDS, prefix, ctx)
        _opt_enum(ann, out, "visual", STRIKETHROUGH_VISUALS, prefix, ctx)

    elif kind == "version_history":
        _opt_enum(ann, out, "kind_subtype", VERSION_HISTORY_SUBTYPES, prefix, ctx)

    elif kind == "definitions":
        _opt_enum(ann, out, "layout", DEFINITIONS_LAYOUTS, prefix, ctx)

    elif kind == "applicability":
        _opt_enum(ann, out, "position", APPLICABILITY_POSITIONS, prefix, ctx)

    elif kind == "priority":
        _opt_enum(ann, out, "position", APPLICABILITY_POSITIONS, prefix, ctx)

    elif kind == "reference_intra_doc":
        _opt_bool(ann, out, "inline", prefix, ctx)
        _apply_target(ann, out, prefix, ctx, kind)

    elif kind == "reference_cross_doc":
        _opt_bool(ann, out, "inline", prefix, ctx)
        _apply_target(ann, out, prefix, ctx, kind)

    elif kind == "reference_spec":
        style = ann.get("style")
        if style not in SPEC_REFERENCE_STYLES:
            ctx.err(
                f"{prefix}.style must be one of {SPEC_REFERENCE_STYLES} for "
                f"kind='reference_spec'; got {style!r}"
            )
        else:
            out["style"] = style
        _opt_bool(ann, out, "inline", prefix, ctx)
        _apply_target(ann, out, prefix, ctx, kind)

    elif kind == "reference_list":
        _opt_enum(
            ann, out, "numbering_style", REFERENCE_LIST_NUMBERING_STYLES, prefix, ctx
        )
        _opt_enum(ann, out, "layout", REFERENCE_LIST_LAYOUTS, prefix, ctx)

    elif kind == "reference_list_entry":
        _opt_int(ann, out, "number", prefix, ctx, lo=0)
        _opt_int(ann, out, "title_hint_chars", prefix, ctx, lo=0)
        _apply_target(ann, out, prefix, ctx, kind)


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def _opt_str(ann, out, key, prefix, ctx):
    v = ann.get(key)
    if v is None:
        return
    if not isinstance(v, str):
        ctx.err(f"{prefix}.{key} must be a string")
        return
    if v:
        out[key] = v


def _opt_int(ann, out, key, prefix, ctx, lo=None, hi=None):
    v = ann.get(key)
    if v is None:
        return
    if not isinstance(v, int) or isinstance(v, bool):
        ctx.err(f"{prefix}.{key} must be an integer")
        return
    if lo is not None and v < lo:
        ctx.err(f"{prefix}.{key} must be >= {lo}")
        return
    if hi is not None and v > hi:
        ctx.err(f"{prefix}.{key} must be <= {hi}")
        return
    out[key] = v


def _opt_bool(ann, out, key, prefix, ctx):
    v = ann.get(key)
    if v is None:
        return
    if not isinstance(v, bool):
        ctx.err(f"{prefix}.{key} must be a boolean")
        return
    out[key] = v


def _opt_enum(ann, out, key, allowed, prefix, ctx):
    v = ann.get(key)
    if v is None:
        return
    if v not in allowed:
        ctx.err(f"{prefix}.{key} must be one of {allowed}; got {v!r}")
        return
    out[key] = v


def _apply_target(ann, out, prefix, ctx, kind):
    """Validate and copy the optional `target` dict for reference-* kinds.

    Unknown keys silently stripped; type-mismatched values flagged.
    """
    target = ann.get("target")
    if target is None:
        return
    if not isinstance(target, dict):
        ctx.err(f"{prefix}.target must be an object")
        return
    allowed = TARGET_KEYS_BY_KIND.get(kind, {})
    clean: dict[str, Any] = {}
    for k, v in target.items():
        if k not in allowed:
            continue  # silently drop unknown keys (forward compatibility)
        expected_type = allowed[k]
        if expected_type is int:
            if not isinstance(v, int) or isinstance(v, bool):
                ctx.err(f"{prefix}.target.{k} must be an integer")
                continue
            clean[k] = v
        else:  # str
            if not isinstance(v, str):
                ctx.err(f"{prefix}.target.{k} must be a string")
                continue
            if v:
                clean[k] = v
    if clean:
        out["target"] = clean
