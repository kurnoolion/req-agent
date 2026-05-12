"""CLI entrypoint for the profile-miner.

Usage:
    # Process every *_corrections.json under <env_dir>/corrections/
    python -m core.src.profile_miner.profile_miner_cli --env-dir <env_dir>

    # Process one doc only
    python -m core.src.profile_miner.profile_miner_cli \\
        --env-dir <env_dir> --doc LTEDATARETRY

    # Force a specific Ollama model instead of the auto-picked one
    python -m core.src.profile_miner.profile_miner_cli \\
        --env-dir <env_dir> --ollama-model llama3:8b

The CLI emits one patch file per document at
``<env_dir>/reports/profile_patch_<doc_id>.json``. A human reviews each
patch and selectively merges entries into
``customizations/profiles/<MNO>_<plan>.json`` before re-running the
parse stage.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path

from core.src.llm.base import LLMProvider
from core.src.llm.model_picker import detect_hardware, pick_model
from core.src.llm.ollama_provider import OllamaProvider
from core.src.profile_miner.loader import load_corrections
from core.src.profile_miner.miner import mine_patterns

logger = logging.getLogger(__name__)


def _build_llm(args: argparse.Namespace) -> LLMProvider:
    """Resolve which LLM provider to use. Defaults to Ollama with
    hardware-aware model auto-picking (matches the existing pipeline
    convention from the collaboration protocol)."""
    if args.ollama_model:
        model = args.ollama_model
    else:
        hw = detect_hardware()
        choice = pick_model(hw)
        model = choice.model
        logger.info(
            "Auto-picked Ollama model %s (%s)", model, choice.reason,
        )
    return OllamaProvider(model=model, base_url=args.ollama_url)


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Mine document-profile regex patterns from human corrections "
            "(<env_dir>/corrections/*_corrections.json)."
        ),
    )
    p.add_argument("--env-dir", required=True, type=Path)
    p.add_argument(
        "--doc", default=None,
        help="Doc id to process (default: every *_corrections.json found)",
    )
    p.add_argument(
        "--ollama-url", default="http://localhost:11434",
        help="Ollama server URL (default: %(default)s)",
    )
    p.add_argument(
        "--ollama-model", default=None,
        help="Force a specific Ollama model (default: auto-pick for hardware)",
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

    enriched = load_corrections(env_dir, args.doc)
    if not enriched:
        print(
            "No corrections to mine. Make sure the Review tab has been "
            "used and saved at least once.",
            file=sys.stderr,
        )
        sys.exit(0)

    # One patch per document so a reviewer can merge per-corpus.
    by_doc: dict[str, list] = defaultdict(list)
    for c in enriched:
        by_doc[c.doc_id].append(c)

    llm = _build_llm(args)

    reports_dir = env_dir / "reports"
    n_written = 0
    for doc_id, items in by_doc.items():
        logger.info("Mining %d corrections for %s", len(items), doc_id)
        patch = mine_patterns(items, llm)
        out_path = reports_dir / f"profile_patch_{doc_id}.json"
        patch.save_json(out_path)
        n_written += 1
        n_unmapped = len(patch.unmapped)
        logger.info(
            "  → %s (%d patches, %d unmapped)",
            out_path, len(patch.field_patches), n_unmapped,
        )

    print(f"Wrote {n_written} profile patch file(s) under {reports_dir}/")


if __name__ == "__main__":
    main()
