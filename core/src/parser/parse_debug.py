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
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# revhist subcommand
# ---------------------------------------------------------------------------

def _load_profile(env_dir: Path):
    from core.src.profiler.profile_schema import DocumentProfile

    candidates = [
        env_dir / "corrections" / "profile.json",
        env_dir / "out" / "profile" / "profile.json",
    ]
    for p in candidates:
        if p.exists():
            return DocumentProfile.load_json(p), p
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

    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        if args.cmd == "revhist":
            rc = cmd_revhist(args)
        else:
            p.error(f"unknown subcommand: {args.cmd}")
            rc = 2
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        rc = 2

    sys.exit(rc)


if __name__ == "__main__":
    main()
