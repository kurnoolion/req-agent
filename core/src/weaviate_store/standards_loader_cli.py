"""CLI entry point for Weaviate Standards content loader.

Reads parsed spec content from data/standards/TS_*/Rel-*/spec_parsed.json
and updates matching placeholder Standards rows in Weaviate.

Run AFTER ingest_cli — placeholder rows must exist before this loader runs.

Usage examples:

    # Local Weaviate (default)
    python -m core.src.weaviate_store.standards_loader_cli \\
        --standards-dir data/standards

    # With verbose logging
    python -m core.src.weaviate_store.standards_loader_cli \\
        --standards-dir data/standards -v

    # Custom Weaviate endpoint
    python -m core.src.weaviate_store.standards_loader_cli \\
        --standards-dir data/standards \\
        --host localhost --port 8080

    # Weaviate Cloud
    python -m core.src.weaviate_store.standards_loader_cli \\
        --standards-dir data/standards \\
        --host my-cluster.weaviate.network \\
        --api-key <WCS_API_KEY>
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load parsed standards content into Weaviate Standards rows.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--standards-dir", type=Path, default=Path("data/standards"),
        metavar="DIR",
        help="Directory containing TS_*/Rel-*/spec_parsed.json files",
    )
    parser.add_argument("--host",      default="localhost", help="Weaviate host")
    parser.add_argument("--port",      type=int, default=8080,  help="Weaviate HTTP port")
    parser.add_argument("--grpc-port", type=int, default=50051, help="Weaviate gRPC port")
    parser.add_argument("--api-key",   default=None, help="Weaviate Cloud API key")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s  %(name)s: %(message)s",
    )

    if not args.standards_dir.exists():
        logging.error("--standards-dir not found: %s", args.standards_dir)
        raise SystemExit(1)

    try:
        import weaviate
    except ImportError:
        logging.error("weaviate-client not installed: pip install weaviate-client")
        raise SystemExit(1)

    from core.src.weaviate_store.standards_loader import StandardsLoader

    # ── Connect ──────────────────────────────────────────────────────────────
    if args.api_key:
        client = weaviate.connect_to_wcs(
            cluster_url=f"https://{args.host}",
            auth_credentials=weaviate.auth.AuthApiKey(args.api_key),
        )
    else:
        client = weaviate.connect_to_local(
            host=args.host,
            port=args.port,
            grpc_port=args.grpc_port,
        )

    # ── Run loader ───────────────────────────────────────────────────────────
    t0 = time.time()
    try:
        with client:
            loader = StandardsLoader(client)
            stats  = loader.load(args.standards_dir)
    except Exception as exc:
        logging.error("Loader failed: %s", exc)
        raise SystemExit(1)

    elapsed = time.time() - t0
    print(
        f"\nDone in {elapsed:.1f}s\n"
        f"  Specs processed   : {stats.specs_processed}\n"
        f"  Rows found        : {stats.rows_found}\n"
        f"  Rows updated      : {stats.rows_updated}\n"
        f"  Already loaded    : {stats.rows_already_loaded}\n"
        f"  Section not found : {stats.section_not_found}\n"
        f"  Errors            : {stats.errors}\n"
    )
    if stats.skipped_specs:
        print("  Skipped:")
        for s in stats.skipped_specs:
            print(f"    {s}")

    if stats.errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
