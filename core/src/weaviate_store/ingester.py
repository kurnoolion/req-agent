"""Weaviate ingestion pipeline for NORA requirement trees.

Loads parsed RequirementTree JSON files, runs CrossReferenceResolver
across the full corpus, then upserts one Weaviate object per requirement.

Each requirement is stored individually — no merged tree is produced.
Resolved cross-reference IDs are attached to each object at ingest time.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

from core.src.parser.structural_parser import RequirementTree, Requirement
from core.src.resolver.resolver import (
    CrossReferenceResolver,
    CrossReferenceManifest,
)
from core.src.weaviate_store.schema import (
    COLLECTION_NAME,
    RequirementObject,
    collection_schema,
)

logger = logging.getLogger(__name__)


# ── Manifest index ──────────────────────────────────────────────────────────


@dataclass
class _ReqRefs:
    internal_ref_ids: list[str]
    cross_plan_ids: list[str]
    standards_specs: list[str]


def _index_manifest(manifest: CrossReferenceManifest) -> dict[str, _ReqRefs]:
    """Build a per-requirement cross-reference lookup from one manifest."""
    idx: dict[str, _ReqRefs] = defaultdict(
        lambda: _ReqRefs([], [], [])
    )

    for ref in manifest.internal_refs:
        idx[ref.source_req_id].internal_ref_ids.append(ref.target_req_id)

    for ref in manifest.cross_plan_refs:
        idx[ref.source_req_id].cross_plan_ids.append(ref.target_plan_id)

    for ref in manifest.standards_refs:
        idx[ref.source_req_id].standards_specs.append(ref.spec)

    return dict(idx)


# ── Object builder ──────────────────────────────────────────────────────────


def _build_object(
    req: Requirement,
    tree: RequirementTree,
    refs: _ReqRefs | None,
) -> RequirementObject:
    r = refs or _ReqRefs([], [], [])
    return RequirementObject(
        req_id=req.req_id,
        plan_id=tree.plan_id,
        mno=tree.mno,
        release=tree.release,
        plan_name=tree.plan_name,
        section_number=req.section_number,
        title=req.title,
        parent_req_id=req.parent_req_id,
        parent_section=req.parent_section,
        hierarchy_path=list(req.hierarchy_path),
        zone_type=req.zone_type,
        priority=req.priority,
        applicability=list(req.applicability),
        text=req.text,
        internal_ref_ids=r.internal_ref_ids,
        cross_plan_ids=r.cross_plan_ids,
        standards_specs=r.standards_specs,
    )


# ── Ingester ────────────────────────────────────────────────────────────────


class WeaviateIngester:
    """Ingest a corpus of RequirementTree objects into Weaviate.

    Args:
        host: Weaviate host (default "localhost").
        port: Weaviate HTTP port (default 8080).
        grpc_port: Weaviate gRPC port (default 50051).
        api_key: Optional Weaviate API key for cloud instances.
        batch_size: Objects per batch flush (default 200).
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8080,
        grpc_port: int = 50051,
        api_key: str | None = None,
        batch_size: int = 200,
    ) -> None:
        self._host = host
        self._port = port
        self._grpc_port = grpc_port
        self._api_key = api_key
        self._batch_size = batch_size
        self._client = None

    # ── Connection lifecycle ────────────────────────────────────────────────

    def connect(self) -> None:
        try:
            import weaviate
            import weaviate.classes as wvc  # noqa: F401 — validate import
        except ImportError as exc:
            raise ImportError(
                "weaviate-client>=4.0.0 required: pip install weaviate-client"
            ) from exc

        if self._api_key:
            auth = weaviate.auth.AuthApiKey(self._api_key)
            self._client = weaviate.connect_to_wcs(
                cluster_url=f"https://{self._host}",
                auth_credentials=auth,
                skip_init_checks=False,
            )
        else:
            self._client = weaviate.connect_to_local(
                host=self._host,
                port=self._port,
                grpc_port=self._grpc_port,
            )

        logger.info(
            f"Connected to Weaviate at {self._host}:{self._port} "
            f"(gRPC {self._grpc_port})"
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> WeaviateIngester:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ── Schema management ───────────────────────────────────────────────────

    def ensure_collection(self, recreate: bool = False) -> None:
        """Create the Requirement collection if absent; optionally recreate."""
        assert self._client is not None, "Call connect() first"

        exists = self._client.collections.exists(COLLECTION_NAME)

        if exists and recreate:
            logger.info(f"Deleting existing collection '{COLLECTION_NAME}'")
            self._client.collections.delete(COLLECTION_NAME)
            exists = False

        if not exists:
            logger.info(f"Creating collection '{COLLECTION_NAME}'")
            self._client.collections.create(**collection_schema())
        else:
            logger.info(f"Collection '{COLLECTION_NAME}' already exists — skipping create")

    # ── Ingest ──────────────────────────────────────────────────────────────

    def ingest(
        self,
        trees: list[RequirementTree],
        *,
        recreate: bool = False,
    ) -> IngestStats:
        """Run the full pipeline: resolve → build objects → upsert.

        Args:
            trees: All RequirementTree objects in the corpus.
            recreate: Drop and recreate the collection before ingesting.

        Returns:
            IngestStats with counts of inserted / errored objects.
        """
        assert self._client is not None, "Call connect() first"

        self.ensure_collection(recreate=recreate)

        # Resolve cross-references across the full corpus
        logger.info(f"Resolving cross-references for {len(trees)} trees")
        resolver = CrossReferenceResolver(trees)
        manifests = resolver.resolve_all()

        # Index manifests by plan_id for O(1) lookup
        manifest_by_plan: dict[str, dict[str, _ReqRefs]] = {}
        for manifest in manifests:
            manifest_by_plan[manifest.plan_id] = _index_manifest(manifest)

        # Build requirement objects
        objects = []
        for tree in trees:
            plan_refs = manifest_by_plan.get(tree.plan_id, {})
            for req in tree.requirements:
                obj = _build_object(req, tree, plan_refs.get(req.req_id))
                objects.append(obj)

        logger.info(
            f"Ingesting {len(objects)} requirements from {len(trees)} trees"
        )

        return self._batch_insert(objects)

    def _batch_insert(self, objects: list[RequirementObject]) -> IngestStats:
        from weaviate.util import generate_uuid5

        collection = self._client.collections.get(COLLECTION_NAME)
        stats = IngestStats(total=len(objects))

        with collection.batch.fixed_size(batch_size=self._batch_size) as batch:
            for obj in objects:
                batch.add_object(
                    properties=obj.to_properties(),
                    uuid=generate_uuid5(obj.uuid_key()),
                )

        # Collect errors from the batch context
        if collection.batch.failed_objects:
            stats.errors = len(collection.batch.failed_objects)
            for err in collection.batch.failed_objects:
                logger.warning(f"Batch error: {err}")

        stats.inserted = stats.total - stats.errors
        logger.info(
            f"Ingest complete: {stats.inserted} inserted, {stats.errors} errors"
        )
        return stats


@dataclass
class IngestStats:
    total: int = 0
    inserted: int = 0
    errors: int = 0
