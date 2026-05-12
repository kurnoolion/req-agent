"""CLI entry point for Weaviate ingestion (6-collection pipeline).

Loads parsed RequirementTree JSON files and resolved cross-reference
manifest JSONs, then runs the 5-phase Weaviate ingestion pipeline.

Usage examples:

    # Ingest from directories (local Weaviate)
    python -m core.src.weaviate_store.ingest_cli \\
        --trees-dir data/parsed \\
        --manifests-dir data/resolved

    # Ingest specific files with recreate
    python -m core.src.weaviate_store.ingest_cli \\
        --trees-dir data/parsed \\
        --manifests-dir data/resolved \\
        --recreate

    # Custom Weaviate endpoint
    python -m core.src.weaviate_store.ingest_cli \\
        --trees-dir data/parsed \\
        --manifests-dir data/resolved \\
        --host localhost --port 8080

    # Weaviate Cloud (WCS)
    python -m core.src.weaviate_store.ingest_cli \\
        --trees-dir data/parsed \\
        --manifests-dir data/resolved \\
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
        description="Ingest parsed requirement trees into Weaviate (6 collections).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # ── Input sources ────────────────────────────────────────────────────────
    tree_group = parser.add_mutually_exclusive_group(required=True)
    tree_group.add_argument(
        "--trees-dir", type=Path, metavar="DIR",
        help="Directory containing *_tree.json files",
    )
    tree_group.add_argument(
        "--trees", nargs="+", type=Path, metavar="FILE",
        help="Explicit paths to *_tree.json files",
    )

    manifest_group = parser.add_mutually_exclusive_group()
    manifest_group.add_argument(
        "--manifests-dir", type=Path, metavar="DIR",
        help="Directory containing *_manifest.json (or *_xrefs.json) files",
    )
    manifest_group.add_argument(
        "--manifests", nargs="+", type=Path, metavar="FILE",
        help="Explicit paths to manifest JSON files",
    )

    # ── Weaviate connection ──────────────────────────────────────────────────
    parser.add_argument("--host",     default="localhost", help="Weaviate host")
    parser.add_argument("--port",     type=int, default=8080,  help="Weaviate HTTP port")
    parser.add_argument("--grpc-port",type=int, default=50051, help="Weaviate gRPC port")
    parser.add_argument("--api-key",  default=None, help="Weaviate Cloud API key")

    # ── Ingestion options ────────────────────────────────────────────────────
    parser.add_argument(
        "--recreate", action="store_true",
        help="Drop and recreate ALL collections before ingesting",
    )
    parser.add_argument(
        "--batch-size", type=int, default=200,
        help="Objects per batch flush",
    )
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s  %(name)s: %(message)s",
    )

    # ── Collect input files ──────────────────────────────────────────────────
    if args.trees_dir:
        tree_files = sorted(args.trees_dir.glob("*_tree.json"))
    else:
        tree_files = list(args.trees)

    if not tree_files:
        logging.error("No *_tree.json files found")
        raise SystemExit(1)

    if args.manifests_dir:
        manifest_files = sorted(args.manifests_dir.glob("*_manifest.json"))
        if not manifest_files:
            manifest_files = sorted(args.manifests_dir.glob("*_xrefs.json"))
    elif args.manifests:
        manifest_files = list(args.manifests)
    else:
        manifest_files = []
        logging.warning(
            "No --manifests-dir / --manifests provided — "
            "depends_on and standards cross-refs will be empty"
        )

    # ── Load trees ───────────────────────────────────────────────────────────
    logging.info("Loading %d tree file(s) …", len(tree_files))
    trees: list[RequirementTree] = []
    for f in tree_files:
        t0 = time.time()
        tree = RequirementTree.load_json(f)
        logging.info(
            "  %-40s  %4d reqs  defs=%d  (%.1fs)",
            f.name,
            len(tree.requirements),
            len(tree.definitions_map),
            time.time() - t0,
        )
        trees.append(tree)

    total_reqs = sum(len(t.requirements) for t in trees)
    logging.info(
        "Loaded %d trees, %d total requirements, %d manifest file(s)",
        len(trees), total_reqs, len(manifest_files),
    )

    # ── Run ingestion ────────────────────────────────────────────────────────
    t0 = time.time()
    with WeaviateIngester(
        host=args.host,
        port=args.port,
        grpc_port=args.grpc_port,
        api_key=args.api_key,
        batch_size=args.batch_size,
    ) as ingester:
        stats = ingester.ingest(
            trees,
            manifest_files=manifest_files or None,
            recreate=args.recreate,
        )

    elapsed = time.time() - t0
    print(
        f"\nDone in {elapsed:.1f}s\n"
        f"  Requirements  : {stats.inserted_requirements}\n"
        f"  Req releases  : {stats.inserted_req_releases}\n"
        f"  Standards     : {stats.inserted_standards}\n"
        f"  Depends-on    : {stats.updated_depends_on}\n"
        f"  Errors        : {stats.errors}\n"
        f"  Skipped (no ID): {stats.skipped_no_req_id}"
    )

    if stats.errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
