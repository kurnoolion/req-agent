"""parse_debug — diagnostic CLI for parser-side detection paths.

First subcommand:

  python -m core.src.parser.parse_debug revhist --env-dir <ENV_DIR> --doc <DOC_ID>

      Walks every TABLE block in <ENV_DIR>/out/extract/<DOC_ID>_ir.json and
      prints, for each, the per-signal breakdown that the active profile's
      RevhistDetection scorer would compute:

        - position fraction (block_index / total_blocks)
        - joined headers
        - merged-cell anchor text(s)
        - first 3 body rows
        - position / vocab / cell sub-scores
        - combined score and whether it clears the threshold

      Use this to diagnose "why doesn't doc X get its revhist detected" —
      surfaces the weakest signal so you can either lower the threshold,
      add a vocab token, or relax the position cutoff.

The CLI emits no proprietary content beyond what's already in the IR;
the user is expected to redact when sharing chunks of this output.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# revhist subcommand
# ---------------------------------------------------------------------------

def _load_profile(env_dir: Path):
    """Load the profile through the same substitution chain the parse
    stage uses (D-062), so placeholder regex fields like
    ``requirement_id.pattern = "<MNO0>_REQ_<PLAN>_\\d+"`` are resolved
    to their real values before parse_debug builds compiled regexes.

    Without this, parse_debug would build ``_req_id_anchored_re`` from
    the literal-placeholder pattern, ``_heading_title_text``'s last-run
    stripping would never match the real-value runs in the IR, and the
    label-path candidate output would show spurious 'miss' verdicts
    that don't reflect what the real parser sees.
    """
    from core.src.profiler.profile_substitute import load_substituted_profile

    candidates = [
        env_dir / "corrections" / "profile.json",
        env_dir / "out" / "profile" / "profile.json",
    ]
    for p in candidates:
        if p.exists():
            return load_substituted_profile(p, env_dir=env_dir), p
    raise FileNotFoundError(
        f"No profile at {candidates[0]} or {candidates[1]}. "
        "Run the profile stage first."
    )


def _load_ir(env_dir: Path, doc_id: str):
    from core.src.models.document import DocumentIR

    p = env_dir / "out" / "extract" / f"{doc_id}_ir.json"
    if not p.exists():
        raise FileNotFoundError(
            f"No IR at {p}. Run the extract stage first."
        )
    return DocumentIR.load_json(p)


def _format_row(cells: list[str], max_cells: int = 6, cell_max: int = 40) -> str:
    cells = list(cells)[:max_cells]
    return " | ".join((c or "")[:cell_max] for c in cells)


def cmd_revhist(args: argparse.Namespace) -> int:
    from core.src.models.document import BlockType
    from core.src.parser.structural_parser import GenericStructuralParser

    env_dir: Path = args.env_dir
    profile, profile_path = _load_profile(env_dir)
    rd = profile.revhist_detection
    parser = GenericStructuralParser(profile)
    ir = _load_ir(env_dir, args.doc)

    total = len(ir.content_blocks)
    print(f"# parse_debug revhist — doc={args.doc!r}")
    print(f"profile: {profile_path}")
    print(f"  revision_history_label_pattern = "
          f"{profile.revision_history_label_pattern!r}")
    print(f"  requirement_id.anchor = "
          f"{profile.requirement_id.anchor!r}")
    print(f"  revhist_detection.enabled = {rd.enabled}")
    print(f"  threshold = {rd.threshold:.2f}  "
          f"weights: position={rd.position_weight} vocab={rd.vocab_weight} "
          f"cell={rd.cell_weight}")
    print(f"  max_position_fraction = {rd.max_position_fraction}")
    print(f"  vocab_tokens ({len(rd.vocab_tokens)}): "
          f"{', '.join(rd.vocab_tokens[:10])}"
          + ("…" if len(rd.vocab_tokens) > 10 else ""))
    print()
    print(f"total content blocks: {total}")
    print()

    # --- Label-path candidates ---
    # Walk every HEADING/PARAGRAPH block whose text looks like it might
    # be a revhist label. Show raw text, the normalized title that the
    # body pass actually tests, and whether the regex matches.
    print("[label-path candidates — text contains 'history' or 'log']")
    label_hits = 0
    for b in ir.content_blocks:
        if b.type not in (BlockType.PARAGRAPH, BlockType.HEADING):
            continue
        t = (b.text or "").lower()
        if not any(k in t for k in ("history", "change log", "revision log",
                                    "version log", "document log")):
            continue
        normalized = parser._heading_title_text(b)
        matches = bool(
            parser._revhist_re
            and parser._revhist_re.match(normalized)
        )
        flag = "✓ MATCH" if matches else "  miss "
        if matches:
            label_hits += 1
        print(f"{flag}  idx={b.position.index:>4d}  "
              f"type={b.type.value:9s}")
        print(f"        raw:        {(b.text or '')[:120]!r}")
        print(f"        normalized: {normalized[:120]!r}")
        if b.runs:
            run_summary = " | ".join(
                f"{r.text[:30]!r}" for r in b.runs[:4]
            )
            print(f"        runs ({len(b.runs)}): {run_summary}")
        print()
    if label_hits == 0:
        print("  (no label-path matches — fall through to table scoring)")
        print()
    else:
        print(f"  total label-path matches: {label_hits}")
        print()

    n_tables = 0
    n_pass = 0
    for b in ir.content_blocks:
        if b.type != BlockType.TABLE or not (b.headers or b.merged_cells):
            continue
        n_tables += 1
        idx = b.position.index
        frac = idx / max(total - 1, 1)
        joined_headers = " | ".join(h.strip() for h in (b.headers or []))
        merged_texts = [
            mc.text for mc in (b.merged_cells or []) if mc.text
        ]
        rows = b.rows or []

        # Always compute the score breakdown, even when revhist_detection
        # is disabled — the user wants to know whether enabling would
        # have caught this table.
        if not parser._revhist_score_enabled:
            # Temporarily enable to compute breakdown.
            parser._revhist_score_enabled = True
            score, breakdown = parser._score_revhist_table(b, total)
            parser._revhist_score_enabled = False
        else:
            score, breakdown = parser._score_revhist_table(b, total)

        clears = score >= rd.threshold
        marker = "✓ PASS" if clears else "  ----"
        if clears:
            n_pass += 1
        print(f"{marker}  idx={idx:>4d}  frac={frac:.2f}  "
              f"score={score:.2f} (pos={breakdown.get('position', 0):.2f} "
              f"vocab={breakdown.get('vocab', 0):.2f} "
              f"cell={breakdown.get('cell', 0):.2f})")
        print(f"        headers: {joined_headers[:120] or '(empty)'}")
        if merged_texts:
            print(f"        merged:  {' || '.join(merged_texts)[:120]}")
        for r_idx, row in enumerate(rows[:3]):
            print(f"        row[{r_idx}]: {_format_row(row)}")
        print()

    print(
        f"summary: {n_tables} TABLE blocks scanned · "
        f"{n_pass} would clear threshold "
        f"({'enabled' if rd.enabled else 'DISABLED — counts hypothetical'})"
    )
    return 0


# ---------------------------------------------------------------------------
# glossary subcommand
# ---------------------------------------------------------------------------

# Proposed defaults for the to-be-built ``GlossaryDetection`` profile
# field. Hardcoded here so parse_debug can preview the scorer's
# behaviour against a real corpus before the profile schema lands.
# When ``GlossaryDetection`` is built, these will move to the schema
# as field defaults and this block deletes.
_GLOSSARY_VOCAB_TOKENS = [
    "acronym", "acronyms",
    "abbrev", "abbreviation", "abbreviations",
    "definition", "definitions",
    "term", "terms",
    "expansion", "expansions",
    "meaning", "meanings",
    "glossary",
    "description",
]

# Col-0 shape: short uppercase / mixed-case acronym tokens. Bounded
# length so prose doesn't slip in.
_GLOSSARY_COL0_ACRONYM_RE = re.compile(r"^[A-Z][A-Za-z0-9/_-]{1,15}$")

# Col-1 shape: prose. Heuristic — any cell with > 8 chars AND >= 1
# whitespace (rules out single-word values).
def _looks_like_prose(text: str) -> bool:
    s = (text or "").strip()
    return len(s) > 8 and any(c.isspace() for c in s)


def _glossary_position_score(frac: float) -> float:
    """Glossaries can sit anywhere — typically Acronyms/Definitions
    section mid-doc or at end. Heuristic: middle-and-back of doc
    favoured slightly. Front-matter (first 15%) gets 0; everywhere
    else gets 1.0. Subject to revision when the real corpus reveals
    a clearer pattern."""
    return 0.0 if frac <= 0.15 else 1.0


def cmd_glossary(args: argparse.Namespace) -> int:
    from core.src.models.document import BlockType

    env_dir: Path = args.env_dir
    profile, profile_path = _load_profile(env_dir)
    ir = _load_ir(env_dir, args.doc)

    total = len(ir.content_blocks)
    print(f"# parse_debug glossary — doc={args.doc!r}")
    print(f"profile: {profile_path}")
    print(f"  heading_detection.definitions_section_pattern = "
          f"{profile.heading_detection.definitions_section_pattern!r}")
    print(f"  heading_detection.definitions_table_header_pattern = "
          f"{profile.heading_detection.definitions_table_header_pattern!r}")
    print(f"  definitions_entry_pattern = "
          f"{profile.definitions_entry_pattern!r}")
    print()
    print(f"# proposed GlossaryDetection scoring defaults (preview — "
          f"not yet in profile schema)")
    print(f"  vocab_tokens ({len(_GLOSSARY_VOCAB_TOKENS)}): "
          f"{', '.join(_GLOSSARY_VOCAB_TOKENS[:8])}…")
    print(f"  col-0 acronym shape: {_GLOSSARY_COL0_ACRONYM_RE.pattern!r}")
    print(f"  col-1 prose heuristic: len>8 AND has whitespace")
    print(f"  position rule: 1.0 if frac > 0.15 else 0.0  "
          f"(glossaries typically mid-doc or end)")
    print()
    print(f"total content blocks: {total}")
    print()

    # --- Label-path candidates --- glossary keywords in heading/paragraph
    print("[label-path candidates — heading/paragraph containing glossary-vocab]")
    label_hits = 0
    section_re = (
        re.compile(profile.heading_detection.definitions_section_pattern)
        if profile.heading_detection.definitions_section_pattern else None
    )
    for b in ir.content_blocks:
        if b.type not in (BlockType.PARAGRAPH, BlockType.HEADING):
            continue
        t = (b.text or "").lower()
        if not any(k in t for k in (
            "glossar", "acronym", "abbrev", "definition",
            "term", "expansion", "meaning",
        )):
            continue
        # _heading_title_text accesses parser-side methods; build a
        # minimal parser instance just for the helper.
        from core.src.parser.structural_parser import GenericStructuralParser
        parser = GenericStructuralParser(profile)
        normalized = parser._heading_title_text(b)
        matches = bool(section_re and section_re.search(normalized))
        flag = "✓ MATCH" if matches else "  miss "
        if matches:
            label_hits += 1
        print(f"{flag}  idx={b.position.index:>4d}  "
              f"type={b.type.value:9s}")
        print(f"        raw:        {(b.text or '')[:120]!r}")
        print(f"        normalized: {normalized[:120]!r}")
        if b.runs:
            run_summary = " | ".join(
                f"{r.text[:30]!r}" for r in b.runs[:4]
            )
            print(f"        runs ({len(b.runs)}): {run_summary}")
        print()
    if label_hits == 0:
        print("  (no label-path matches — fall through to table-header / score)")
        print()
    else:
        print(f"  total label-path matches: {label_hits}")
        print()

    # --- Table-header regex check (D-069 path) ---
    print("[table-header regex path — joined headers vs definitions_table_header_pattern]")
    table_header_re = (
        re.compile(profile.heading_detection.definitions_table_header_pattern)
        if profile.heading_detection.definitions_table_header_pattern else None
    )
    if table_header_re is None:
        print("  (definitions_table_header_pattern is empty — path disabled)")
        print()
    else:
        any_hit = False
        for b in ir.content_blocks:
            if b.type != BlockType.TABLE or not b.headers:
                continue
            joined = " | ".join(h.strip() for h in b.headers)
            if table_header_re.search(joined):
                any_hit = True
                idx = b.position.index
                frac = idx / max(total - 1, 1)
                print(f"  ✓ MATCH  idx={idx}  frac={frac:.2f}")
                print(f"           headers: {joined[:120]}")
        if not any_hit:
            print("  (no joined-header match)")
        print()

    # --- Per-TABLE proposed-score breakdown ---
    print("[per-TABLE proposed-score preview — "
          "position + vocab + cell-fingerprint]")
    n_tables = 0
    n_pass = 0
    threshold = 0.55  # mirror RevhistDetection default
    for b in ir.content_blocks:
        if b.type != BlockType.TABLE or not (b.headers or b.merged_cells):
            continue
        n_tables += 1
        idx = b.position.index
        frac = idx / max(total - 1, 1)
        joined_headers = " | ".join(h.strip() for h in (b.headers or []))
        merged_texts = [mc.text for mc in (b.merged_cells or []) if mc.text]
        rows = b.rows or []

        # Position
        pos_score = _glossary_position_score(frac)

        # Vocab — scan headers + merged-cell text + body cells, like
        # revhist post-a8ed9cf.
        body_text = " || ".join(
            " | ".join(str(c).strip() for c in row if c)
            for row in rows if row
        )
        haystack = (
            joined_headers + " || " + " || ".join(merged_texts)
            + " || " + body_text
        ).lower()
        hits = set()
        for tok in _GLOSSARY_VOCAB_TOKENS:
            if re.search(r"\b" + re.escape(tok) + r"\b", haystack):
                hits.add(tok)
        vocab_score = min(len(hits), 4) / 4.0  # cap at 4, normalize

        # Cell fingerprint — col 0 acronym-shape, col 1 prose-shape.
        # Each column contributes 0.5 if its shape gate fires for
        # ≥50% of body cells (so 1.0 cap when both fire).
        cell_score = 0.0
        if rows and any(row for row in rows):
            for col_idx, gate, weight in [
                (0, _GLOSSARY_COL0_ACRONYM_RE.match, 0.5),
                (1, lambda v: _looks_like_prose(v), 0.5),
            ]:
                col_vals = [
                    str(row[col_idx]).strip()
                    for row in rows if len(row) > col_idx and row[col_idx]
                ]
                if not col_vals:
                    continue
                match_frac = sum(1 for v in col_vals if gate(v)) / len(col_vals)
                if match_frac >= 0.5:
                    cell_score += weight

        combined = (
            pos_score * 0.20
            + vocab_score * 0.50
            + cell_score * 0.30
        )
        clears = combined >= threshold
        marker = "✓ PASS" if clears else "  ----"
        if clears:
            n_pass += 1
        print(f"{marker}  idx={idx:>4d}  frac={frac:.2f}  "
              f"score={combined:.2f} "
              f"(pos={pos_score:.2f} vocab={vocab_score:.2f} cell={cell_score:.2f})")
        print(f"        headers: {joined_headers[:120] or '(empty)'}")
        if merged_texts:
            print(f"        merged:  {' || '.join(merged_texts)[:120]}")
        if hits:
            print(f"        vocab hits ({len(hits)}): "
                  f"{', '.join(sorted(hits))}")
        for r_idx, row in enumerate(rows[:3]):
            row_repr = " | ".join(
                (str(c).strip() or '')[:40] for c in list(row)[:6]
            )
            print(f"        row[{r_idx}]: {row_repr}")
        print()

    print(
        f"summary: {n_tables} TABLE blocks scanned · "
        f"{n_pass} would clear threshold {threshold:.2f}  "
        f"(preview — GlossaryDetection not yet in profile schema)"
    )
    return 0


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        prog="parse_debug",
        description="Diagnostic CLI for parser-side detection paths.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    rh = sub.add_parser(
        "revhist",
        help="Show per-table RevhistDetection signal breakdown for one doc.",
    )
    rh.add_argument("--env-dir", required=True, type=Path)
    rh.add_argument(
        "--doc", required=True,
        help="Doc id (the stem of <env_dir>/out/extract/<doc>_ir.json)",
    )

    gl = sub.add_parser(
        "glossary",
        help="Show glossary detection diagnostics (label / table-header / "
             "preview scoring) for one doc. Preview uses proposed defaults "
             "since GlossaryDetection isn't in the profile schema yet.",
    )
    gl.add_argument("--env-dir", required=True, type=Path)
    gl.add_argument(
        "--doc", required=True,
        help="Doc id (the stem of <env_dir>/out/extract/<doc>_ir.json)",
    )

    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        if args.cmd == "revhist":
            rc = cmd_revhist(args)
        elif args.cmd == "glossary":
            rc = cmd_glossary(args)
        else:
            p.error(f"unknown subcommand: {args.cmd}")
            rc = 2
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        rc = 2

    sys.exit(rc)


if __name__ == "__main__":
    main()
