"""CLI entrypoint for the profile-miner.

Usage:
    # Process every *_corrections.json under <env_dir>/corrections/
    python -m core.src.profile_miner.profile_miner_cli --env-dir <env_dir>

    # Process one doc only
    python -m core.src.profile_miner.profile_miner_cli \\
        --env-dir <env_dir> --doc LTEDATARETRY

    # Override the LLM provider / model resolved from config + env
    python -m core.src.profile_miner.profile_miner_cli \\
        --env-dir <env_dir> \\
        --llm-provider openai-compatible --llm-model gpt-4o-mini

Provider / model resolution follows the project-wide chain (D-044):
CLI flag > config/llm.json > matching NORA_LLM_* env var > built-in
default. Same path the pipeline runner and web UI use.

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

from core.src.env.config import (
    resolve_llm_model,
    resolve_llm_provider,
    resolve_llm_timeout,
)
from core.src.llm.base import LLMProvider
from core.src.pipeline.runner import PipelineContext
from core.src.profile_miner.loader import load_corrections
from core.src.profile_miner.miner import mine_patterns

logger = logging.getLogger(__name__)


def _build_llm(args: argparse.Namespace) -> LLMProvider:
    """Resolve LLM provider + model via the project-wide chain (D-044)
    so envvars and config/llm.json actually take effect. CLI flags
    win, then config/llm.json, then NORA_LLM_* env vars, then defaults."""
    provider_name = resolve_llm_provider(cli_value=args.llm_provider)
    model = resolve_llm_model(cli_value=args.llm_model)
    timeout = resolve_llm_timeout(cli_value=args.llm_timeout)
    ctx = PipelineContext(
        documents_dir=Path("."),
        corrections_dir=None,
        eval_dir=None,
        verbose=args.verbose,
        model_provider=provider_name,
        model_name=model,
        model_timeout=timeout,
    )
    logger.info(
        "Resolved LLM: provider=%s model=%s timeout=%ss",
        provider_name, model, timeout,
    )
    return ctx.create_llm_provider(require_real=True)


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
        "--llm-provider", default=None,
        help="Override resolved LLM provider (ollama | openai-compatible | mock)",
    )
    p.add_argument(
        "--llm-model", default=None,
        help="Override resolved LLM model name",
    )
    p.add_argument(
        "--llm-timeout", default=None, type=int,
        help="Override resolved LLM request timeout in seconds",
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
