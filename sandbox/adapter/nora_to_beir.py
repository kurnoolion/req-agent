"""NORA → BEIR adapter for the SIRA standalone-sandbox experiment.

Reads parsed `_tree.json` artifacts from `<env_dir>/out/parse/` and emits
the four files in the SIRA-internal `raw/` layout:

  <out>/raw/corpus.jsonl         — one row per Requirement {_id, title, text}
  <out>/raw/queries-test.jsonl   — one row per eval question {_id, text}
                                    (from `core.src.eval.questions`)
  <out>/raw/qrels-test.jsonl     — {query-id, corpus-id, score} per qrel
                                    (score=1 for every expected req_id;
                                    relevance is binary)
  <out>/raw/metadata.json        — {name, source, num_corpus, splits}

When `<out>/raw/metadata.json` exists, SIRA's `scripts/prepare_mteb_data.py`
early-returns ("Already prepared at … — skipping download.") so the full
hydra pipeline (`scripts/run_pipeline.py data=nora ...`) runs unchanged
against our local data. No HuggingFace download happens.

Corpus row shape — `{"_id": req_id, "title": "<section_num section_title>",
"text": "<markdown body>"}`. The body is constructed as:

    # {section_number} {section_title}
    **req_id**: {req_id}
    **plan**: {plan_name or plan_id}
    **hierarchy**: {parent_section path}

    {body text with inline acronym expansion per chunk_builder D-032 / D-043}

    **Cross-refs**: {comma-joined internal req_ids + standards specs}

Acronym expansion uses `core.src.vectorstore.chunk_builder._expand_definitions`
directly — guarantees parity with NORA's BM25 lane (apples-to-apples test
per strand decision).

Locked strand decisions reflected here:
  * acronym pre-expansion ON (D-032/D-043 inline format)
  * heading-only reqs INCLUDED (title becomes the text)
  * struck reqs naturally absent (parser drops per D-031/D-037)
  * combined corpus across all parsed plans (18-Q eval spans plans)
  * `_id` = req_id so the qrels join works cleanly

Usage:
    python -m sandbox.adapter.nora_to_beir \\
        --env-dir <env_dir> \\
        --output sandbox/adapter/out/nora_beir
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from core.src.vectorstore.chunk_builder import ChunkBuilder


# We need ChunkBuilder's two static helpers; importing them by reference
# avoids re-implementing the regex compile + expansion logic.
_compile_defs = ChunkBuilder._compile_definitions_regex
_expand_defs = ChunkBuilder._expand_definitions


def _load_trees(env_dir: Path) -> list[dict[str, Any]]:
    parse_dir = env_dir / "out" / "parse"
    if not parse_dir.is_dir():
        raise FileNotFoundError(
            f"No parse output at {parse_dir} — run the parse stage first."
        )
    trees: list[dict[str, Any]] = []
    for p in sorted(parse_dir.glob("*_tree.json")):
        with open(p, "r", encoding="utf-8") as f:
            trees.append(json.load(f))
    return trees


def _hierarchy_path(req: dict[str, Any]) -> str:
    # Tree stores `hierarchy_path` as a list of strings (e.g. ["LTE OTA",
    # "Idle Mode", "T3402 timer"]). Joined with " > " for prose
    # readability; empty when the req sits at the doc root.
    h = req.get("hierarchy_path") or []
    return " > ".join(str(x) for x in h if x)


def _cross_refs_line(req: dict[str, Any]) -> str:
    xr = req.get("cross_references") or {}
    parts: list[str] = []
    for rid in (xr.get("internal") or [])[:8]:
        parts.append(str(rid))
    for plan in (xr.get("external_plans") or [])[:8]:
        parts.append(str(plan))
    for s in (xr.get("standards") or [])[:8]:
        spec = s.get("spec", "")
        sect = s.get("section", "")
        if spec and sect:
            parts.append(f"{spec} §{sect}")
        elif spec:
            parts.append(spec)
    return ", ".join(parts)


def _build_text(req: dict[str, Any], tree: dict[str, Any],
                defs_re: "re.Pattern | None",
                definitions_map: dict[str, str]) -> str:
    """Markdown body for one corpus row."""
    section_num = req.get("section_number") or ""
    title = req.get("title") or ""
    req_id = req.get("req_id") or ""
    plan = tree.get("plan_name") or tree.get("plan_id") or ""
    hierarchy = _hierarchy_path(req)
    body = req.get("text") or ""
    if defs_re is not None and body:
        body = _expand_defs(body, defs_re, definitions_map)

    lines = [f"# {section_num} {title}".strip()]
    if req_id:
        lines.append(f"**req_id**: {req_id}")
    if plan:
        lines.append(f"**plan**: {plan}")
    if hierarchy:
        lines.append(f"**hierarchy**: {hierarchy}")
    if body:
        lines.append("")
        lines.append(body)
    xref = _cross_refs_line(req)
    if xref:
        lines.append("")
        lines.append(f"**Cross-refs**: {xref}")
    return "\n".join(lines)


def _emit_corpus(trees: list[dict[str, Any]], out_path: Path) -> int:
    seen_ids: set[str] = set()
    written = 0
    skipped_no_id = 0
    skipped_dup = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for tree in trees:
            definitions_map = tree.get("definitions_map") or {}
            defs_re = _compile_defs(definitions_map) if definitions_map else None
            for req in tree.get("requirements") or []:
                req_id = (req.get("req_id") or "").strip()
                if not req_id:
                    skipped_no_id += 1
                    continue
                if req_id in seen_ids:
                    # Same req_id reported by two trees: keep first.
                    # Cross-doc dedup avoids the corpus polluting itself
                    # with parser-stage hierarchy duplicates.
                    skipped_dup += 1
                    continue
                seen_ids.add(req_id)
                title = (
                    f"{(req.get('section_number') or '').strip()} "
                    f"{(req.get('title') or '').strip()}"
                ).strip()
                row = {
                    "_id": req_id,
                    "title": title,
                    "text": _build_text(req, tree, defs_re, definitions_map),
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
    print(f"  corpus.jsonl: wrote {written} rows "
          f"(skipped: {skipped_no_id} no-id, {skipped_dup} duplicate)")
    return written


def _emit_queries_and_qrels(
    raw_dir: Path, split: str = "test",
) -> tuple[int, int, int]:
    """Returns (n_queries, n_qrels, n_queries_with_no_qrels)."""
    # Lazy import — the eval module pulls in heavy deps at top.
    from core.src.eval import questions as eval_q

    all_questions = [
        v for k, v in vars(eval_q).items()
        if k.startswith("Q_") and isinstance(v, eval_q.EvalQuestion)
    ]
    all_questions.sort(key=lambda q: q.id)

    queries_path = raw_dir / f"queries-{split}.jsonl"
    qrels_path = raw_dir / f"qrels-{split}.jsonl"

    n_qrels = 0
    n_queries = 0
    n_no_qrels = 0
    with open(queries_path, "w", encoding="utf-8") as qf, \
         open(qrels_path, "w", encoding="utf-8") as rf:
        for q in all_questions:
            qf.write(json.dumps({"_id": q.id, "text": q.question},
                                ensure_ascii=False) + "\n")
            n_queries += 1
            req_ids = q.ground_truth.expected_req_ids or []
            if not req_ids:
                n_no_qrels += 1
                continue
            for rid in req_ids:
                rf.write(json.dumps(
                    {"query-id": q.id, "corpus-id": rid, "score": 1}
                ) + "\n")
                n_qrels += 1
    print(f"  queries-{split}.jsonl: wrote {n_queries} queries "
          f"({n_no_qrels} have no expected_req_ids → not in qrels)")
    print(f"  qrels-{split}.jsonl: wrote {n_qrels} qrel rows")
    return n_queries, n_qrels, n_no_qrels


def _emit_metadata(raw_dir: Path, name: str, num_corpus: int,
                   n_queries: int, n_qrels: int, split: str = "test") -> None:
    """Write metadata.json mirroring `prepare_mteb_data.py`'s shape.

    SIRA's `prepare_mteb_data.py` early-returns when this file exists,
    so the rest of the pipeline runs against our local data without
    triggering a HuggingFace download.
    """
    metadata = {
        "name": name,
        "source": "nora-local-adapter",
        "num_corpus": num_corpus,
        "splits": {
            split: {"num_queries": n_queries, "num_qrels": n_qrels},
        },
    }
    with open(raw_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)


def main() -> int:
    p = argparse.ArgumentParser(
        prog="nora_to_beir",
        description=(
            "Convert NORA parse output + 18-Q eval set into BEIR-format "
            "corpus.jsonl + queries.jsonl + qrels/test.tsv for the SIRA "
            "standalone sandbox."
        ),
    )
    p.add_argument("--env-dir", required=True, type=Path,
                   help="NORA env dir containing out/parse/*_tree.json")
    p.add_argument("--output", required=True, type=Path,
                   help=(
                       "Output dir for the SIRA-internal layout. The "
                       "dir's basename becomes the dataset 'name' SIRA "
                       "uses (override with --name). raw/ subdir holds "
                       "corpus.jsonl, queries-test.jsonl, "
                       "qrels-test.jsonl, metadata.json."
                   ))
    p.add_argument("--name", default=None,
                   help="Dataset name in metadata.json. Defaults to "
                        "the basename of --output.")
    args = p.parse_args()
    if args.name is None:
        args.name = args.output.name

    env_dir: Path = args.env_dir
    out_dir: Path = args.output
    raw_dir = out_dir / "raw"

    print(f"# nora_to_beir")
    print(f"env_dir: {env_dir}")
    print(f"output:  {out_dir}  (SIRA-internal layout under raw/)")
    print()

    trees = _load_trees(env_dir)
    print(f"loaded {len(trees)} _tree.json file(s) from out/parse/")
    print()

    raw_dir.mkdir(parents=True, exist_ok=True)
    print("emitting raw/corpus.jsonl ...")
    num_corpus = _emit_corpus(trees, raw_dir / "corpus.jsonl")
    print()
    print("emitting raw/queries-test.jsonl + raw/qrels-test.jsonl ...")
    n_queries, n_qrels, _ = _emit_queries_and_qrels(raw_dir)
    print()
    print("emitting raw/metadata.json ...")
    _emit_metadata(raw_dir, name=args.name, num_corpus=num_corpus,
                   n_queries=n_queries, n_qrels=n_qrels)
    print()
    print(f"done — point SIRA at db_root={out_dir.parent}, data.name={args.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
