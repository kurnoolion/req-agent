"""CLI entry point for Weaviate ingestion.

Loads parsed RequirementTree JSON files, resolves cross-references, and
upserts one Weaviate object per requirement.

Usage:
    # Ingest all trees in a directory (Weaviate running locally)
    python -m core.src.weaviate_store.ingest_cli \\
        --trees-dir data/parsed

    # Ingest with custom Weaviate endpoint and recreate collection
    python -m core.src.weaviate_store.ingest_cli \\
        --trees-dir data/parsed \\
        --host localhost --port 8080 \\
        --recreate

    # Weaviate Cloud (WCS) instance
    python -m core.src.weaviate_store.ingest_cli \\
        --trees-dir data/parsed \\
        --host my-cluster.weaviate.network \\
        --api-key <WCS_API_KEY>
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from core.src.parser.structural_parser import RequirementTree
from core.src.weaviate_store.ingester import WeaviateIngester


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest parsed requirement trees into Weaviate."
    )

    # Input
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--trees-dir", type=Path,
        help="Directory containing *_tree.json files",
    )
    group.add_argument(
        "--trees", nargs="+", type=Path,
        help="Paths to specific tree JSON files",
    )

    # Weaviate connection
    parser.add_argument(
        "--host", default="localhost",
        help="Weaviate host. Default: localhost",
    )
    parser.add_argument(
        "--port", type=int, default=8080,
        help="Weaviate HTTP port. Default: 8080",
    )
    parser.add_argument(
        "--grpc-port", type=int, default=50051,
        help="Weaviate gRPC port. Default: 50051",
    )
    parser.add_argument(
        "--api-key", default=None,
        help="Weaviate API key (for WCS cloud instances)",
    )

    # Ingestion options
    parser.add_argument(
        "--recreate", action="store_true",
        help="Drop and recreate the Requirement collection before ingesting",
    )
    parser.add_argument(
        "--batch-size", type=int, default=200,
        help="Objects per batch flush. Default: 200",
    )

    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # Collect tree files
    if args.trees_dir:
        tree_files = sorted(args.trees_dir.glob("*_tree.json"))
    else:
        tree_files = list(args.trees)

    if not tree_files:
        logging.error("No tree files found")
        raise SystemExit(1)

    # Load trees
    logging.info(f"Loading {len(tree_files)} tree file(s)")
    trees: list[RequirementTree] = []
    for f in tree_files:
        t0 = time.time()
        tree = RequirementTree.load_json(f)
        logging.info(
            f"  {f.name}: {len(tree.requirements)} requirements "
            f"({time.time() - t0:.1f}s)"
        )
        trees.append(tree)

    total_reqs = sum(len(t.requirements) for t in trees)
    logging.info(f"Total: {len(trees)} trees, {total_reqs} requirements")

    # Ingest
    t0 = time.time()
    with WeaviateIngester(
        host=args.host,
        port=args.port,
        grpc_port=args.grpc_port,
        api_key=args.api_key,
        batch_size=args.batch_size,
    ) as ingester:
        stats = ingester.ingest(trees, recreate=args.recreate)

    elapsed = time.time() - t0
    logging.info(
        f"\nDone in {elapsed:.1f}s — "
        f"{stats.inserted} inserted, {stats.errors} errors "
        f"(total={stats.total})"
    )

    if stats.errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
