"""Test page — multi-section playground for free-form requirement
queries with thumbs-up/down feedback capture.

Currently only the `requirement_bot` section is functional; other
section IDs are placeholders rendered as "Coming soon" in the
template. Each Q&A pair is logged to `<env_dir>/state/
nora_test_feedback.db` via `FeedbackStore`; the user's later
thumbs-up/down + free-form feedback updates the same row.

The Requirement Bot reuses the production query path
(`_run_query_sync` in routes/query.py) so the test page exercises
the same retrieval/synthesis stack as `/query`. The test page
adds: per-Q&A persistence + a feedback widget. It does NOT add
a job queue — calls block synchronously until the answer arrives,
which is the expected UX for a "ask + read + vote" interaction.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _corpus_label() -> str:
    """Best-effort short label for the corpus the web UI is bound to.

    Reads the active ``EnvironmentConfig.mnos`` + ``.releases`` lists
    when an env config can be located for the configured ``env_dir``;
    otherwise returns ``"the indexed"`` so the blurb stays grammatical.

    Format:
      * Single MNO + single release: ``"VZW Feb2026"``.
      * Multi-MNO or multi-release: ``"<N MNOs × M releases>"``.
      * Unknown: ``"the indexed"``.
    """
    try:
        from core.src.web.routes.query import _find_env_config_for_web
        env_cfg = _find_env_config_for_web()
    except Exception as e:  # pragma: no cover — defensive
        logger.debug("corpus label: env-config lookup failed (%s)", e)
        return "the indexed"
    if env_cfg is None:
        return "the indexed"
    mnos = [m for m in (env_cfg.mnos or []) if m]
    releases = [r for r in (env_cfg.releases or []) if r]
    if len(mnos) == 1 and len(releases) == 1:
        return f"{mnos[0]} {releases[0]}"
    if mnos and releases:
        return f"{len(mnos)} MNOs × {len(releases)} releases"
    return "the indexed"


def _build_sections() -> list[dict[str, Any]]:
    """Build the per-request section registry with a corpus-aware blurb.

    Sections are otherwise static (handlers wired in ``_run_section()``);
    only the ``requirement_bot`` blurb is dynamic so the Test page
    reflects what's actually ingested on-prem instead of a hardcoded
    corpus name.
    """
    label = _corpus_label()
    return [
        {
            "id": "requirement_bot",
            "label": "Requirement Bot",
            "enabled": True,
            "blurb": (
                f"Ask any free-form question about the {label} "
                "requirements corpus. The answer is synthesized from "
                "retrieved chunks; rate it below to log feedback for "
                "offline review."
            ),
        },
        {
            "id": "compliance_check",
            "label": "Compliance Check",
            "enabled": False,
            "blurb": "Single-requirement compliance against device specs.",
        },
        {
            "id": "cross_mno_compare",
            "label": "Cross-MNO Compare",
            "enabled": False,
            "blurb": "Compare requirement coverage across operators.",
        },
        {
            "id": "standards_lookup",
            "label": "Standards Lookup",
            "enabled": False,
            "blurb": "Look up 3GPP TS section text by spec + section.",
        },
    ]


# Section IDs are static — only the blurb on requirement_bot is dynamic;
# this constant survives only as a quick id-validity check.
_SECTION_IDS: set[str] = {
    "requirement_bot",
    "compliance_check",
    "cross_mno_compare",
    "standards_lookup",
}


# -- Pages ------------------------------------------------------------------


@router.get("/test", response_class=HTMLResponse)
async def playground_page(request: Request, section: str = "requirement_bot"):
    from core.src.web.app import _template_response

    # Default to first enabled section if user passed an unknown id
    active_section = section if section in _SECTION_IDS else "requirement_bot"

    return _template_response(request, "test/index.html", {
        "sections": _build_sections(),
        "active_section": active_section,
    })


# -- API: ask + feedback ----------------------------------------------------


@router.post("/api/test/ask", response_class=HTMLResponse)
async def playground_ask(request: Request):
    """Submit a question, run the query pipeline, log the Q&A row,
    return rendered answer + citations + feedback widget seeded with
    the row id."""
    from core.src.web.app import _template_response

    form = await request.form()
    question = (form.get("question") or "").strip()
    section = (form.get("section") or "requirement_bot").strip()

    if not question:
        return _template_response(request, "test/_answer.html", {
            "error": "Question is required.",
        })

    # Hand off to the section's runner. Currently only requirement_bot
    # is wired; other sections are tab-disabled in the template, but
    # an explicit POST against them returns a friendly stub.
    if section != "requirement_bot":
        return _template_response(request, "test/_answer.html", {
            "error": f"Section '{section}' is not yet implemented.",
        })

    # Run the query (blocks the request — sync-style UX). Reuses the
    # existing /query path's pipeline construction.
    start = time.time()
    try:
        result = await asyncio.to_thread(_run_query_for_test, question, request.app)
    except Exception as e:
        logger.exception("Test query failed")
        return _template_response(request, "test/_answer.html", {
            "error": f"Query failed: {e}",
        })
    elapsed_ms = int((time.time() - start) * 1000)

    if "error" in result:
        return _template_response(request, "test/_answer.html", {
            "error": result["error"],
        })

    # Persist the Q&A row. The feedback widget renders below with the
    # returned row id; the user's vote later updates this row in
    # place.
    feedback_store = request.app.state.feedback_store
    row_id = await feedback_store.record_qa(
        section=section,
        question=question,
        answer=result.get("answer", ""),
        citations=result.get("citations", []),
        query_elapsed_ms=elapsed_ms,
        llm_model=result.get("llm_model"),
        metadata={"candidate_count": result.get("candidate_count")},
    )

    return _template_response(request, "test/_answer.html", {
        "row_id": row_id,
        "question": question,
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "llm_citations": result.get("llm_citations", []),
        "rag_chunks": result.get("rag_chunks", []),
        "rag_chunk_count": result.get("rag_chunk_count", 0),
        "elapsed_ms": elapsed_ms,
        "candidate_count": result.get("candidate_count"),
        "section": section,
        "disambiguation_required": result.get("disambiguation_required", False),
        "groups": result.get("groups", []),
        "llm_system_prompt": result.get("llm_system_prompt", ""),
        "llm_context_text": result.get("llm_context_text", ""),
        "citation_audit": result.get("citation_audit"),
    })


@router.post("/api/test/synthesize-group", response_class=HTMLResponse)
async def playground_synthesize_group(request: Request):
    """Step 3c — user picked a group from a disambiguation response.

    Form fields:
      - `question`: original query (so the answer addresses it)
      - `chunk_ids`: comma-separated chunk_ids of the picked group
      - `section`: same as /api/test/ask, passed through

    Re-runs the query with `pinned_chunk_ids` set, which skips Stages
    2-4.7 and synthesizes only from those chunks.
    """
    from core.src.web.app import _template_response

    form = await request.form()
    question = (form.get("question") or "").strip()
    chunk_ids_raw = (form.get("chunk_ids") or "").strip()
    section = (form.get("section") or "requirement_bot").strip()

    if not question:
        return _template_response(request, "test/_answer.html", {
            "error": "Question is required.",
        })
    if not chunk_ids_raw:
        return _template_response(request, "test/_answer.html", {
            "error": "No chunk_ids provided. Pick a group first.",
        })

    chunk_ids = [c.strip() for c in chunk_ids_raw.split(",") if c.strip()]
    if not chunk_ids:
        return _template_response(request, "test/_answer.html", {
            "error": "chunk_ids empty after parse.",
        })

    start = time.time()
    try:
        result = await asyncio.to_thread(
            _run_query_for_test, question, request.app, chunk_ids,
        )
    except Exception as e:
        logger.exception("Synthesize-group query failed")
        return _template_response(request, "test/_answer.html", {
            "error": f"Query failed: {e}",
        })
    elapsed_ms = int((time.time() - start) * 1000)

    if "error" in result:
        return _template_response(request, "test/_answer.html", {
            "error": result["error"],
        })

    feedback_store = request.app.state.feedback_store
    row_id = await feedback_store.record_qa(
        section=section,
        question=question,
        answer=result.get("answer", ""),
        citations=result.get("citations", []),
        query_elapsed_ms=elapsed_ms,
        llm_model=result.get("llm_model"),
        metadata={
            "candidate_count": result.get("candidate_count"),
            "synthesize_group": True,
            "pinned_chunk_count": len(chunk_ids),
        },
    )

    return _template_response(request, "test/_answer.html", {
        "row_id": row_id,
        "question": question,
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "llm_citations": result.get("llm_citations", []),
        "rag_chunks": result.get("rag_chunks", []),
        "rag_chunk_count": result.get("rag_chunk_count", 0),
        "elapsed_ms": elapsed_ms,
        "candidate_count": result.get("candidate_count"),
        "section": section,
        # On the synthesis re-run, disambiguation cannot fire (we're
        # past it), so these are always defaults — pass them through
        # for template consistency.
        "disambiguation_required": False,
        "groups": [],
        "llm_system_prompt": result.get("llm_system_prompt", ""),
        "llm_context_text": result.get("llm_context_text", ""),
        "citation_audit": result.get("citation_audit"),
    })


@router.post("/api/test/feedback", response_class=HTMLResponse)
async def playground_feedback(
    request: Request,
    row_id: int = Form(...),
    vote: str = Form(""),
    free_form_feedback: str = Form(""),
):
    """Update an existing Q&A row with the user's vote / comment.
    Returns a small confirmation HTML fragment for HTMX swap."""
    from core.src.web.app import _template_response

    vote_clean = vote.strip().lower() or None
    if vote_clean not in ("up", "down", None):
        return _template_response(request, "test/_feedback_ack.html", {
            "error": f"Invalid vote: {vote!r}",
        })

    feedback_store = request.app.state.feedback_store
    try:
        ok = await feedback_store.record_feedback(
            row_id=row_id,
            vote=vote_clean,
            free_form_feedback=(free_form_feedback or "").strip() or None,
        )
    except Exception as e:
        logger.exception("Feedback persist failed")
        return _template_response(request, "test/_feedback_ack.html", {
            "error": f"Could not save feedback: {e}",
        })

    if not ok:
        return _template_response(request, "test/_feedback_ack.html", {
            "error": f"No feedback row with id={row_id}",
        })

    return _template_response(request, "test/_feedback_ack.html", {
        "row_id": row_id,
        "vote": vote_clean,
    })


# -- Helpers ----------------------------------------------------------------


def _run_query_for_test(
    question: str,
    app=None,
    pinned_chunk_ids: list[str] | None = None,
) -> dict:
    """Adapt the existing /query pipeline runner into a dict shape
    the test page templates can consume directly. Re-imports the
    helper from the query module so we don't fork pipeline
    construction logic. `app` is passed through so the cached
    pipeline on `app.state` is reused across requests.

    Surfaces three citation views to the template:
      - `citations`: legacy combined list (LLM-cited + fallback)
      - `llm_citations`: subset cited explicitly in the answer text
      - `rag_chunks`: every chunk RAG returned (with text for the
        click-to-expand fragment view)

    Step 3c additions:
      - `disambiguation_required`, `groups` — surfaced when the pipeline
        short-circuits at Stage 4.7 with multiple plausible groups.
      - `pinned_chunk_ids` parameter — when set, the pipeline skips
        retrieval and synthesizes only from those chunks (used after
        the user picks a group from a disambiguation response).
    """
    from core.src.web.routes.query import _run_query_sync

    raw = _run_query_sync(question, app=app, pinned_chunk_ids=pinned_chunk_ids)
    if "error" in raw:
        return {"error": raw["error"]}

    # _run_query_sync may attach _llm_metrics; pop it (we don't
    # display it on the test page).
    raw.pop("_llm_metrics", None)

    return {
        "answer": raw.get("answer", ""),
        "citations": raw.get("citations", []) or [],
        "llm_citations": raw.get("llm_citations", []) or [],
        "rag_chunks": raw.get("rag_chunks", []) or [],
        "rag_chunk_count": raw.get("rag_chunk_count", 0),
        "candidate_count": raw.get("candidate_count"),
        "llm_model": raw.get("llm_model"),
        "disambiguation_required": raw.get("disambiguation_required", False),
        "groups": raw.get("groups", []),
        "llm_system_prompt": raw.get("llm_system_prompt", ""),
        "llm_context_text": raw.get("llm_context_text", ""),
        "citation_audit": raw.get("citation_audit"),
    }
