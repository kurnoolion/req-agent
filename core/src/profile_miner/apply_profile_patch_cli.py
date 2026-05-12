"""CLI: apply ``profile_patch_<doc>.json`` files onto
``<env_dir>/corrections/profile.json``.

Usage:
    # Merge every profile_patch_*.json under <env_dir>/reports/
    python -m core.src.profile_miner.apply_profile_patch_cli \\
        --env-dir <env_dir>

    # Merge a single doc's patch only
    python -m core.src.profile_miner.apply_profile_patch_cli \\
        --env-dir <env_dir> --doc LTEDATARETRY

    # Preview without writing
    python -m core.src.profile_miner.apply_profile_patch_cli \\
        --env-dir <env_dir> --dry-run

Behaviour:
- For each ``ProfileFieldPatch`` in each patch file:
  - Scalar field, target empty / unset → set directly.
  - Scalar field, target already equals proposal → no-op.
  - Scalar field, target differs → alternation-merge
    (``(?i)(?:<existing>|<new>)``, with shared leading ``(?i)``
    deduplicated).
  - List field (e.g. ``cross_reference_patterns.standards_citations``)
    → append the proposed pattern if not already present.
- ``unmapped`` entries are reported but not applied — the reviewer must
  place those manually.
- The corrections profile is **seeded** from ``<env_dir>/out/profile/*.json``
  on first use; subsequent invocations modify it in place.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from core.src.profile_miner.apply_patch import apply_patch_files

logger = logging.getLogger(__name__)


def _format_value(v) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(repr(x) for x in v) + "]"
    s = repr(v)
    return s if len(s) <= 80 else s[:77] + "…"


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Merge profile_patch_*.json files into "
            "<env_dir>/corrections/profile.json."
        ),
    )
    p.add_argument("--env-dir", required=True, type=Path)
    p.add_argument(
        "--doc", default=None,
        help="Doc id to apply (default: every profile_patch_*.json found)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Report what would change without writing",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    env_dir: Path = args.env_dir
    if not env_dir.is_dir():
        print(f"env_dir not found: {env_dir}", file=sys.stderr)
        sys.exit(2)

    try:
        report, corrections_path = apply_patch_files(
            env_dir,
            doc_id=args.doc,
            dry_run=args.dry_run,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)

    if corrections_path is None:
        print(
            "No profile_patch_*.json files found under "
            f"{env_dir}/reports/. Run profile_miner first.",
            file=sys.stderr,
        )
        sys.exit(0)

    # Group changes by action for a tidy summary.
    by_action: dict[str, list] = {}
    for c in report.changes:
        by_action.setdefault(c.action, []).append(c)

    print(f"\nCorrections profile: {corrections_path}")
    print(f"Mode: {'DRY-RUN (no write)' if args.dry_run else 'APPLIED'}")
    print(f"Total changes: {len(report.changes)}")

    for action in ("set", "merged", "appended",
                   "skipped:already-present", "skipped:unmapped"):
        items = by_action.get(action, [])
        if not items:
            continue
        print(f"\n[{action}]  ({len(items)})")
        for c in items:
            src = f" (from {c.source_doc})" if c.source_doc else ""
            print(f"  · {c.profile_field}{src}")
            if action in ("merged", "set", "appended"):
                print(f"      old: {_format_value(c.old_value)}")
                print(f"      new: {_format_value(c.new_value)}")

    if report.skipped_unmapped:
        print(
            f"\n{len(report.skipped_unmapped)} unmapped field(s) in patches "
            "— place these manually in the profile JSON:"
        )
        for f in report.skipped_unmapped:
            print(f"  · {f}")

    if args.dry_run and report.modified:
        print(
            "\nNo changes written (dry-run). Re-run without --dry-run "
            "to apply."
        )


if __name__ == "__main__":
    main()
