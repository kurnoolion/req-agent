"""SIRA per-query inference service — for NORA's Test page SIRA tab.

Loads SIRA's BM25 index + corpus + telecom prompts once at startup,
exposes `POST /sira-query` for interactive per-query retrieval.
Mirrors the same end-to-end pipeline SIRA's batch scripts run:

    1. Query enrichment via LLM (uses `query_requirement_v01.txt`)
    2. DF-filter the expansion phrases via bm25x.filter_query_expansion
    3. BM25 search with weighted expansion via bm25x.search_with_expansion
    4. LLM pointwise rerank of top_n candidates (uses `relevance_requirement_v01.txt`)
    5. Return top_k ranked results

All LLM calls go through the existing FastAPI shim on port 8030.

Run (from the sandbox/sira/.venv):

    source ~/work/nora/sandbox/activate.sh
    export NORA_SIRA_DB_ROOT=$HOME/work/nora/sandbox/adapter/out
    uvicorn sandbox.sira_query.service:app --port 8040

NORA's Test page (`/test`) gets a SIRA tab that posts to this service.
See sandbox/SETUP.md "Per-query SIRA probe" for the full setup.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Config from env ─────────────────────────────────────────────────

_DB_ROOT = os.getenv("NORA_SIRA_DB_ROOT", "")
_DATASET = os.getenv("NORA_SIRA_DATASET", "nora")
_SHIM_URL = os.getenv("NORA_LLM_SHIM_URL", "http://127.0.0.1:8030").rstrip("/")
_SHIM_MODEL = os.getenv("NORA_LLM_MODEL", "")

# Defaults to ../sira/ relative to this file (the upstream clone).
_SIRA_CLONE_ROOT = Path(os.getenv(
    "NORA_SIRA_CLONE_ROOT",
    str(Path(__file__).resolve().parents[1] / "sira"),
))
_QUERY_PROMPT_PATH = os.getenv(
    "NORA_QUERY_PROMPT",
    "scripts/configs/enrich/prompts/query_requirement_v01.txt",
)
_RERANK_PROMPT_PATH = os.getenv(
    "NORA_RERANK_PROMPT",
    "scripts/configs/rerank/prompts/relevance_requirement_v01.txt",
)

# SIRA pipeline knobs — defaults chosen for interactive use, not eval.
# Rerank top_n in particular needs to be small for interactive: at
# concurrency=1 + ~36s/call (proxy-throttled work-PC environment),
# top_n=200 means ~2 hours per query. top_n=20 is ~12 min — slow but
# tolerable for a diagnostic probe.
_MAX_DF_RATIO = float(os.getenv("NORA_SIRA_MAX_DF_RATIO", "0.05"))
_EXPANSION_WEIGHT = float(os.getenv("NORA_SIRA_EXPANSION_WEIGHT", "0.5"))
_DEFAULT_TOP_K = int(os.getenv("NORA_SIRA_TOP_K", "10"))
_RERANK_TOP_N = int(os.getenv("NORA_SIRA_RERANK_TOP_N", "20"))


# ── Lazy-loaded state ──────────────────────────────────────────────

_bm25 = None
_doc_ids: list[str] = []
_corpus_by_id: dict[str, dict[str, str]] = {}
_query_prompt_template: str = ""
_rerank_prompt_template: str = ""
_max_df_absolute: int = 0
_load_error: str | None = None


def _load_state() -> None:
    """Load BM25 index + corpus + prompts. Called once on first use.

    All errors are stashed in `_load_error` rather than raising, so
    /healthz can report them — `uvicorn` shouldn't crash on a partial
    setup; the user can curl healthz to see what's missing.
    """
    global _bm25, _max_df_absolute, _query_prompt_template, _rerank_prompt_template, _load_error
    if _bm25 is not None:
        return

    if not _DB_ROOT:
        _load_error = (
            "NORA_SIRA_DB_ROOT not set. Point at the adapter output, "
            "e.g. ~/work/nora/sandbox/adapter/out"
        )
        return

    base = Path(_DB_ROOT) / _DATASET
    corpus_path = base / "raw" / "corpus.jsonl"
    index_dir = base / "index" / "best"

    if not corpus_path.exists():
        _load_error = f"corpus.jsonl not found at {corpus_path}"
        return
    if not index_dir.exists():
        _load_error = (
            f"BM25 index not found at {index_dir}. "
            "Run `python scripts/eval_bm25.py data=nora db_root=…` first."
        )
        return

    # Corpus: build id → {title, text} mapping
    with open(corpus_path, encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            rid = obj["_id"]
            _doc_ids.append(rid)
            _corpus_by_id[rid] = {
                "title": obj.get("title", ""),
                "text": obj.get("text", ""),
            }
    _max_df_absolute = max(1, int(len(_doc_ids) * _MAX_DF_RATIO))

    # BM25 index
    from bm25x import BM25
    _bm25 = BM25.load(str(index_dir))

    # Prompts (telecom variants from sandbox/prompts/, copied into the
    # SIRA clone by install_configs.sh).
    qp = _SIRA_CLONE_ROOT / _QUERY_PROMPT_PATH
    rp = _SIRA_CLONE_ROOT / _RERANK_PROMPT_PATH
    _query_prompt_template = qp.read_text(encoding="utf-8") if qp.exists() else ""
    _rerank_prompt_template = rp.read_text(encoding="utf-8") if rp.exists() else ""
    if not _query_prompt_template:
        logger.warning("Query enrichment prompt not found at %s — expansion stage skipped", qp)
    if not _rerank_prompt_template:
        logger.warning("Reranker prompt not found at %s — rerank stage skipped", rp)

    _load_error = None
    logger.info(
        "SIRA query service ready — corpus=%d docs, max_df=%d, expansion_weight=%.2f, top_n=%d",
        len(_doc_ids), _max_df_absolute, _EXPANSION_WEIGHT, _RERANK_TOP_N,
    )


# ── FastAPI app ────────────────────────────────────────────────────

app = FastAPI(title="NORA SIRA per-query probe")


class _SiraQueryRequest(BaseModel):
    query: str
    top_k: int | None = None


@app.on_event("startup")
def _startup() -> None:
    try:
        _load_state()
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("Startup load failed")
        global _load_error
        _load_error = f"unexpected: {exc}"


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "ok": _bm25 is not None,
        "load_error": _load_error,
        "db_root": _DB_ROOT,
        "dataset": _DATASET,
        "corpus_size": len(_doc_ids),
        "max_df_ratio": _MAX_DF_RATIO,
        "max_df_absolute": _max_df_absolute,
        "expansion_weight": _EXPANSION_WEIGHT,
        "default_top_k": _DEFAULT_TOP_K,
        "rerank_top_n": _RERANK_TOP_N,
        "shim_url": _SHIM_URL,
        "shim_model": _SHIM_MODEL or "(unset — falls back to whatever the shim sends)",
        "query_prompt_loaded": bool(_query_prompt_template),
        "rerank_prompt_loaded": bool(_rerank_prompt_template),
    }


# ── LLM call helpers ───────────────────────────────────────────────

async def _llm_call(
    client: httpx.AsyncClient,
    prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.0,
) -> str:
    """One OpenAI-shaped chat-completion call via the shim. Returns
    the `choices[0].message.content` string."""
    payload: dict[str, Any] = {
        "model": _SHIM_MODEL or "sira-shim",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    resp = await client.post(
        f"{_SHIM_URL}/v1/chat/completions", json=payload,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"shim returned {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"] or ""


def _parse_phrases(raw: str) -> list[str]:
    """Mirror sira.llm.parse_phrases — pull `keywords` list from a
    JSON object embedded in the LLM response."""
    end_char = {"{": "}", "[": "]"}
    for start in ("{", "["):
        idx = raw.find(start)
        if idx == -1:
            continue
        end = raw.rfind(end_char[start])
        if end <= idx:
            continue
        try:
            parsed = json.loads(raw[idx : end + 1])
            if isinstance(parsed, dict):
                parsed = parsed.get("keywords", [])
            if isinstance(parsed, list):
                return [p for p in parsed if isinstance(p, str) and p.strip()]
        except json.JSONDecodeError:
            continue
    return []


def _parse_score(raw: str) -> int:
    """Pull integer `score` from a JSON object in the LLM response.
    Returns 0 on any parse failure (matches SIRA's reranker behavior)."""
    idx = raw.find("{")
    end = raw.rfind("}")
    if idx == -1 or end <= idx:
        return 0
    try:
        obj = json.loads(raw[idx : end + 1])
        return int(obj.get("score", 0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return 0


# ── Main endpoint ──────────────────────────────────────────────────

@app.post("/sira-query")
async def sira_query(req: _SiraQueryRequest) -> dict[str, Any]:
    """Run the full SIRA pipeline on a single query and return the
    top-K reranked results.

    Pipeline:
        1. Query enrichment (LLM call → DF-filter → tokenize)
        2. BM25 search with expansion (top_n candidates)
        3. LLM pointwise rerank of those candidates
        4. Sort by rerank score, return top_k
    """
    _load_state()
    if _load_error:
        raise HTTPException(status_code=503, detail=_load_error)

    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query is empty")

    top_k = req.top_k if (req.top_k and req.top_k > 0) else _DEFAULT_TOP_K
    top_n = max(top_k, _RERANK_TOP_N)
    timings: dict[str, int] = {}
    notes: list[str] = []

    async with httpx.AsyncClient(timeout=300.0) as client:
        # 1. Query enrichment ---------------------------------------
        t0 = time.time()
        kept_phrases: list[str] = []
        expansion_terms = ""
        if _query_prompt_template:
            try:
                prompt = _query_prompt_template.format(doc_text=req.query, max_n=4)
                raw = await _llm_call(client, prompt, max_tokens=512, temperature=0.4)
                proposed = _parse_phrases(raw)
                # DF-filter via bm25x — exactly what the batch script does.
                kept_phrases, _rejected = _bm25.filter_query_expansion(
                    req.query, proposed, _max_df_absolute,
                )
                kept_stems: list[str] = []
                for p in kept_phrases:
                    kept_stems.extend(_bm25.tokenize(p))
                expansion_terms = " ".join(kept_stems) if kept_stems else ""
            except Exception as exc:
                notes.append(f"query-enrich failed (continuing without expansion): {exc}")
        else:
            notes.append("query enrichment prompt missing — search runs without expansion")
        timings["expand_ms"] = int((time.time() - t0) * 1000)

        # 2. BM25 search with expansion -----------------------------
        t0 = time.time()
        try:
            results = _bm25.search_with_expansion(
                [req.query], [expansion_terms],
                k=top_n, weight=_EXPANSION_WEIGHT,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"bm25 search failed: {exc}")
        hits: list[tuple[int, float]] = list(results[0])
        timings["search_ms"] = int((time.time() - t0) * 1000)

        # 3. LLM rerank ---------------------------------------------
        # IMPORTANT: at concurrency=1 (default in our nora.yaml for
        # proxy-throttled environments) this stage is the slow one —
        # top_n × ~per_call_latency. We process serially via asyncio
        # but each call still goes one-at-a-time through the shim.
        # Per-call timing is collected for the response so the user
        # can see the latency distribution + any outliers.
        t0 = time.time()
        reranked: list[tuple[int, float, int]] = []
        rerank_call_ms: list[int] = []
        if _rerank_prompt_template and hits:
            try:
                for idx, score in hits:
                    rid = _doc_ids[idx]
                    doc = _corpus_by_id[rid]
                    # Mirror SIRA's batch reranker — title + body, capped at 4000 chars.
                    doc_text = (f"{doc['title']}\n\n{doc['text']}")[:4000]
                    prompt = _rerank_prompt_template.format(
                        query=req.query, document=doc_text,
                    )
                    call_t0 = time.time()
                    try:
                        raw = await _llm_call(client, prompt, max_tokens=64, temperature=0.0)
                        rerank_score = _parse_score(raw)
                    except Exception as exc:
                        notes.append(f"rerank failed for {rid}: {exc}")
                        rerank_score = 0
                    rerank_call_ms.append(int((time.time() - call_t0) * 1000))
                    reranked.append((idx, score, rerank_score))
                # Sort by rerank score desc, then BM25 desc as tiebreaker.
                reranked.sort(key=lambda x: (-x[2], -x[1]))
            except Exception as exc:
                notes.append(f"rerank stage aborted: {exc}")
                reranked = [(idx, score, 0) for idx, score in hits]
        else:
            if not _rerank_prompt_template:
                notes.append("rerank prompt missing — results are BM25-with-expansion only")
            reranked = [(idx, score, 0) for idx, score in hits]
        timings["rerank_ms"] = int((time.time() - t0) * 1000)

    # Compute rerank-call statistics for instrumentation surface.
    def _pct(sorted_xs: list[int], p: float) -> int:
        if not sorted_xs:
            return 0
        k = max(0, min(len(sorted_xs) - 1, int(round(p * (len(sorted_xs) - 1)))))
        return sorted_xs[k]

    rerank_call_stats: dict[str, Any] = {}
    if rerank_call_ms:
        sorted_ms = sorted(rerank_call_ms)
        rerank_call_stats = {
            "count": len(sorted_ms),
            "total_ms": sum(sorted_ms),
            "min_ms": sorted_ms[0],
            "max_ms": sorted_ms[-1],
            "mean_ms": int(sum(sorted_ms) / len(sorted_ms)),
            "p50_ms": _pct(sorted_ms, 0.50),
            "p95_ms": _pct(sorted_ms, 0.95),
            # Full ordered list — query-order, not sorted — so a user
            # can spot if e.g. the first 3 calls were slow then it
            # smoothed out (cold start) or if there's a degraded tail.
            "call_ms": rerank_call_ms,
        }
        logger.info(
            "sira-query rerank: count=%d total=%dms mean=%dms p50=%dms p95=%dms max=%dms",
            len(sorted_ms), sum(sorted_ms),
            rerank_call_stats["mean_ms"],
            rerank_call_stats["p50_ms"],
            rerank_call_stats["p95_ms"],
            sorted_ms[-1],
        )

    # Format final response -----------------------------------------
    out: list[dict[str, Any]] = []
    for rank, (idx, bm25_score, rerank_score) in enumerate(reranked[:top_k], 1):
        rid = _doc_ids[idx]
        doc = _corpus_by_id[rid]
        text_preview = doc["text"].replace("\n", " ").strip()[:400]
        out.append({
            "rank": rank,
            "req_id": rid,
            "rerank_score": rerank_score,
            "bm25_score": round(float(bm25_score), 4),
            "title": doc["title"],
            "text_preview": text_preview,
        })

    return {
        "query": req.query,
        "top_k": top_k,
        "candidates_reranked": len(reranked),
        "expansion_phrases_kept": kept_phrases,
        "results": out,
        "timings_ms": timings,
        "rerank_call_stats": rerank_call_stats,
        "notes": notes,
    }
