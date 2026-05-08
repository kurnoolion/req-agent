"""Config page — read/edit configurable knobs persisted to the
user-config SQLite DB.

Routes:
  GET  /config              — render the page (form per module section)
  POST /api/config/save     — persist edits + invalidate caches +
                              clear the cached query pipeline so the
                              next request rebuilds with new values

The DB is opt-in (--config-db / $NORA_CONFIG_DB). When disabled the
page renders read-only with a notice asking the admin to set the
path. Read values still come from the live resolver chain so the
page stays useful as a "what's effective right now?" view.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from core.src.web.config_schema import (
    CONFIG_SECTIONS,
    ConfigField,
    find_field,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Read helpers ─────────────────────────────────────────────


def _current_value(field: ConfigField) -> Any:
    """Read the live effective value for a field via the resolver chain.

    Used to seed the form. Falls through CLI flag (n/a here) > env
    var > DB > config file > default; whichever wins is what shows
    in the input.

    For `kind="dict_by_query_type"` returns a dict keyed by
    QueryType.value with the effective per-type value (DB / cache
    overlay > pipeline built-in > 0.0). Pre-populates every
    QueryType so the table editor renders all rows.
    """
    from core.src.env import config as env_cfg

    try:
        if field.kind == "dict_by_query_type":
            return _current_dict_by_query_type(field)
        if field.module == "llm":
            cfg = env_cfg._llm_config()
            return getattr(cfg, field.key, None)
        if field.module == "retrieval":
            cfg = env_cfg._retrieval_config()
            return getattr(cfg, field.key, None)
        if field.module == "pipeline":
            # pipeline knobs aren't on a cached dataclass; resolve via
            # the same paths the web pipeline-build uses.
            if field.key == "max_distance_threshold":
                from core.src.web.routes.query import _resolve_max_distance_threshold
                return _resolve_max_distance_threshold()
            if field.key == "top_k_cap":
                from core.src.web.routes.query import _resolve_top_k_cap
                return _resolve_top_k_cap()
    except Exception as e:
        logger.debug("current_value(%s, %s) failed: %s", field.module, field.key, e)
    return None


def _current_dict_by_query_type(field: ConfigField) -> dict[str, Any]:
    """Build the {query_type: value} dict for a dict_by_query_type
    field, with current effective values for every QueryType."""
    from core.src.query.schema import QueryType
    out: dict[str, Any] = {}
    for qt in QueryType:
        # Each known field has a corresponding resolver path. We hard-
        # code the wiring here (one branch per field) rather than
        # generic introspection — keeps the dispatch explicit.
        if field.module == "retrieval" and field.key == "bm25_weight_by_type":
            from core.src.env.config import resolve_bm25_weight
            out[qt.value] = resolve_bm25_weight(query_type=qt.value)
        else:
            out[qt.value] = 0.0
    return out


# ── Form value coercion ──────────────────────────────────────


def _coerce(field: ConfigField, raw: str) -> Any:
    """Convert a form string to the field's typed value. Empty string
    becomes None for nullable fields, 0 / False for typed defaults
    where appropriate. Raises ValueError on parse failure (caught by
    the route)."""
    if field.kind == "bool":
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    raw = raw.strip()
    if raw == "":
        if field.kind in ("int",):
            return 0
        if field.kind in ("float",):
            return None  # threshold disable signal
        return ""
    if field.kind == "int":
        return int(raw)
    if field.kind == "float":
        return float(raw)
    if field.kind == "enum":
        if field.choices and raw not in field.choices:
            raise ValueError(
                f"{field.label}: {raw!r} not in {field.choices}"
            )
        return raw
    # string / password
    return raw


# ── Routes ───────────────────────────────────────────────────


@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    from core.src.web.app import _template_response

    cs = getattr(request.app.state, "config_store", None)
    db_enabled = cs is not None

    # Build the per-section view — for each field, current value +
    # field metadata so the template can render the right input.
    sections_view = []
    for section in CONFIG_SECTIONS:
        # Group fields by category for layout (Features / Values / Tunables).
        by_category: dict[str, list] = {"feature": [], "value": [], "tunable": []}
        for f in section.fields:
            current = _current_value(f)
            # For dict-by-query-type fields, surface per-row entries
            # so the template can iterate them in deterministic order.
            type_rows = []
            if f.kind == "dict_by_query_type" and isinstance(current, dict):
                from core.src.query.schema import QueryType
                for qt in QueryType:
                    val = current.get(qt.value, 0.0)
                    type_rows.append({
                        "query_type": qt.value,
                        "value_str": ("" if val is None
                                      else str(val)),
                    })
            # For checkboxes / enums the value drives the rendered state.
            by_category[f.category].append({
                "field": f,
                "current": current,
                "current_str": "" if current is None else str(current),
                "is_truthy": bool(current),
                "type_rows": type_rows,
            })
        sections_view.append({
            "module": section.module,
            "title": section.title,
            "description": section.description,
            "features": by_category["feature"],
            # NB: keyed as `value_items`, not `values`, because Jinja
            # resolves `section.values` to the dict's `.values()` method
            # before the "values" key — TypeError on iteration.
            "value_items": by_category["value"],
            "tunables": by_category["tunable"],
        })

    return _template_response(request, "config.html", {
        "db_enabled": db_enabled,
        "db_path": str(cs._path) if db_enabled else None,
        "sections": sections_view,
    })


@router.post("/api/config/save", response_class=HTMLResponse)
async def config_save(request: Request):
    """Persist edits, invalidate caches, clear cached pipeline.

    Form data shape: each input is named "<module>__<key>"; checkboxes
    are present in the form when checked, absent when unchecked (so we
    iterate the schema, not the form, to ensure unchecked toggles
    persist as False).
    """
    from core.src.web.app import _template_response

    cs = getattr(request.app.state, "config_store", None)
    if cs is None:
        return _template_response(request, "_config_save_ack.html", {
            "error": (
                "No ConfigStore configured. Restart the web app with "
                "--config-db /path/to/config.db (or set $NORA_CONFIG_DB) "
                "to enable persistence."
            ),
        })

    form = await request.form()
    submitted_by = (form.get("_submitted_by") or "").strip() or "anonymous"

    updates: list[tuple[str, str, Any]] = []
    errors: list[str] = []

    # Iterate the schema so unchecked checkboxes are explicitly written
    # as False. (Form omits unchecked checkboxes entirely.)
    from core.src.query.schema import QueryType
    from core.src.web.config_schema import all_fields
    for f in all_fields():
        if f.kind == "dict_by_query_type":
            # Collect per-QueryType inputs into a single dict.
            by_type: dict[str, Any] = {}
            row_errors: list[str] = []
            for qt in QueryType:
                row_form_key = f"{f.module}__{f.key}__{qt.value}"
                row_raw = (form.get(row_form_key) or "").strip()
                if row_raw == "":
                    continue  # empty cell → skip; resolver falls back to default
                try:
                    if f.value_kind == "float":
                        by_type[qt.value] = float(row_raw)
                    elif f.value_kind == "int":
                        by_type[qt.value] = int(row_raw)
                    elif f.value_kind == "bool":
                        by_type[qt.value] = row_raw.lower() in {"1", "true", "yes", "on"}
                    else:
                        by_type[qt.value] = row_raw
                except (ValueError, TypeError) as e:
                    row_errors.append(f"{f.label}/{qt.value}: {e}")
            if row_errors:
                errors.extend(row_errors)
                continue
            updates.append((f.module, f.key, by_type))
            continue

        form_key = f"{f.module}__{f.key}"
        if f.kind == "bool":
            raw = "1" if form.get(form_key) else "0"
        else:
            raw = form.get(form_key, "")
            if raw is None:
                continue
        try:
            value = _coerce(f, str(raw))
        except (ValueError, TypeError) as e:
            errors.append(f"{f.label}: {e}")
            continue
        updates.append((f.module, f.key, value))

    if errors:
        return _template_response(request, "_config_save_ack.html", {
            "error": " · ".join(errors),
        })

    # Persist + overlay onto caches.
    for module, key, value in updates:
        cs.set(module, key, value, updated_by=submitted_by)
        cs.reapply_one(module, key)

    # Invalidate the cached query pipeline so the next query rebuilds
    # with the new resolved values. The Web LLM resolution log line
    # will print again on first query.
    if hasattr(request.app.state, "query_pipeline"):
        request.app.state.query_pipeline = None
        logger.info("Config saved: invalidated app.state.query_pipeline")

    return _template_response(request, "_config_save_ack.html", {
        "saved_count": len(updates),
    })
