"""Multi-collection Weaviate ingestion pipeline for NORA.

Ingestion phases (run in order — cross-ref targets must exist before refs):
  Phase 1 — Standards placeholder rows (one per citation instance)
  Phase 2 — RequirementRelease rows   (one per unique content version)
  Phase 3 — Requirement rows          (latest release + cross-refs to 1, 2)
  Phase 4 — Update Requirement.depends_on[] (after all Req rows exist)
  Phase 5 — CarrierRelease upsert     (one row per carrier)

Inputs:
  trees     — list[RequirementTree] loaded from *_tree.json
  manifests — list[CrossReferenceManifest] loaded from *_manifest.json

Key design decisions:
  - Vectorizer.none(): vectors supplied externally (BM25 works without them)
  - req_text: [Path: ...] + [Req ID: ...] + title + definitions-expanded body
  - Definitions expansion: first occurrence of each acronym inline-expanded
  - depends_on: internal req-to-req deps only (resolved, not broken)
  - Standards rows: placeholder (content_available=False) until spec content loaded
  - standard_type: "3GPP" or "ETSI" only — OMADM excluded by design
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.src.parser.structural_parser import RequirementTree, Requirement
from core.src.weaviate_store.schema import (
    REQUIREMENT,
    REQUIREMENT_RELEASE,
    STANDARDS,
    CARRIER_RELEASE,
    SCHEMAS,
    CREATION_ORDER,
)

logger = logging.getLogger(__name__)


# ── Definitions expansion (borrowed from vectorstore/chunk_builder.py) ────────


def _compile_definitions_regex(definitions_map: dict[str, str]):
    """Compile alternation regex for all defined terms (longest-first).

    Returns None when the map is empty.
    """
    if not definitions_map:
        return None
    terms_sorted = sorted(definitions_map.keys(), key=len, reverse=True)
    alternation = "|".join(re.escape(t) for t in terms_sorted)
    return re.compile(rf"\b({alternation})\b")


def _expand_definitions(
    text: str,
    pattern: "re.Pattern[str]",
    definitions_map: dict[str, str],
) -> str:
    """Inline-expand first occurrence of each known term in text.

    ETWS → ETWS (Earthquake and Tsunami Warning System).
    Idempotent: subsequent occurrences within the same chunk are left as-is.
    """
    seen: set[str] = set()

    def repl(m: "re.Match[str]") -> str:
        term = m.group(1)
        if term in seen:
            return term
        seen.add(term)
        expansion = definitions_map.get(term, "")
        return f"{term} ({expansion})" if expansion else term

    return pattern.sub(repl, text)


# ── Table serialization (borrowed from vectorstore/chunk_builder.py) ──────────


def _table_to_markdown(table) -> str:
    """Serialize a TableData object to a Markdown table string."""
    headers = getattr(table, "headers", None) or []
    rows = getattr(table, "rows", None) or []

    if not rows:
        return ""

    # All-empty headers — compact artifact table
    if headers and all(h == "" for h in headers):
        all_cells = [cell for row in rows for cell in row if cell.strip()]
        return ("[Table: " + " | ".join(all_cells) + "]") if all_cells else ""

    if not headers:
        return "\n".join("| " + " | ".join(str(c) for c in row) + " |" for row in rows)

    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        padded = list(row) + [""] * (len(headers) - len(row))
        lines.append("| " + " | ".join(str(c) for c in padded[: len(headers)]) + " |")
    return "\n".join(lines)


# ── req_text builder ──────────────────────────────────────────────────────────


def _build_req_text(
    req: Requirement,
    definitions_map: dict[str, str],
    defs_pattern,
) -> str:
    """Build vectorizable req_text for a single requirement.

    Format (per design decision — no MNO/release/plan header):
        [Path: ZONE > SUBSECTION > LEAF]
        [Req ID: VZ_REQ_PLAN_1234]

        <title>

        <definitions-expanded body text>
    """
    parts: list[str] = []

    # Hierarchy path
    if req.hierarchy_path:
        parts.append(f"[Path: {' > '.join(req.hierarchy_path)}]")

    # Requirement ID
    if req.req_id:
        parts.append(f"[Req ID: {req.req_id}]")

    # Title
    if req.title:
        parts.append(f"\n{req.title}")

    # Body text with definitions expansion
    body = (req.text or "").strip()
    if body and defs_pattern is not None:
        body = _expand_definitions(body, defs_pattern, definitions_map)
    if body:
        parts.append(body)

    return "\n".join(parts)


# ── Content hash ──────────────────────────────────────────────────────────────


def _content_hash(req_text: str, req_tables: list[str], image_captions: str) -> str:
    """SHA-256 of combined req content — used for RequirementRelease deduplication."""
    combined = req_text + "\x00".join(req_tables) + image_captions
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


# ── Standards helpers ─────────────────────────────────────────────────────────

_SPEC_PREFIX_RE = re.compile(r"^(3GPP|ETSI)\s+(?:TS|TR|EN|ES)\s+(.+)$")


def _parse_spec(spec: str) -> tuple[str, str] | None:
    """Return (standard_type, doc_id) or None if not 3GPP/ETSI.

    Skips OMADM and any unknown prefixes — only 3GPP and ETSI go to Weaviate.
    """
    m = _SPEC_PREFIX_RE.match(spec.strip())
    if not m:
        return None
    return m.group(1), m.group(2).strip()  # ("3GPP", "24.301")


def _standards_uuid_key(carrier: str, req_id: str, spec: str, content_type: str, content_id: str) -> str:
    return f"{carrier}:{req_id}:{spec}:{content_type}:{content_id}"


# ── Stats ─────────────────────────────────────────────────────────────────────


@dataclass
class IngestStats:
    trees_loaded: int = 0
    manifests_loaded: int = 0
    total_requirements: int = 0
    inserted_standards: int = 0
    inserted_req_releases: int = 0
    inserted_requirements: int = 0
    updated_depends_on: int = 0
    errors: int = 0
    skipped_no_req_id: int = 0


# ── Ingester ──────────────────────────────────────────────────────────────────


class WeaviateIngester:
    """Ingest NORA requirement trees into Weaviate (6 collections).

    Args:
        host:       Weaviate host (default "localhost").
        port:       HTTP port (default 8080).
        grpc_port:  gRPC port (default 50051).
        api_key:    API key for Weaviate Cloud (None for local).
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

    # ── Connection lifecycle ───────────────────────────────────────────────────

    def connect(self) -> None:
        try:
            import weaviate
        except ImportError as exc:
            raise ImportError(
                "weaviate-client>=4.0.0 required: pip install weaviate-client"
            ) from exc

        if self._api_key:
            self._client = weaviate.connect_to_wcs(
                cluster_url=f"https://{self._host}",
                auth_credentials=weaviate.auth.AuthApiKey(self._api_key),
            )
        else:
            self._client = weaviate.connect_to_local(
                host=self._host,
                port=self._port,
                grpc_port=self._grpc_port,
            )
        logger.info("Connected to Weaviate at %s:%d (gRPC %d)", self._host, self._port, self._grpc_port)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> WeaviateIngester:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ── Schema management ──────────────────────────────────────────────────────

    def ensure_collections(self, recreate: bool = False) -> None:
        """Create all 6 collections in dependency order; optionally recreate."""
        assert self._client is not None, "Call connect() first"

        if recreate:
            # Delete in reverse order (referencing before referenced)
            for name in reversed(CREATION_ORDER):
                if self._client.collections.exists(name):
                    logger.info("Deleting collection '%s'", name)
                    self._client.collections.delete(name)

        for name in CREATION_ORDER:
            if not self._client.collections.exists(name):
                logger.info("Creating collection '%s'", name)
                schema_fn = SCHEMAS[name]
                kwargs = schema_fn()
                # Separate references from properties for the v4 API
                refs = kwargs.pop("references", [])
                self._client.collections.create(**kwargs, references=refs)
            else:
                logger.info("Collection '%s' already exists — skipping", name)

    # ── Main entry point ───────────────────────────────────────────────────────

    def ingest(
        self,
        trees: list[RequirementTree],
        manifest_files: list[Path] | None = None,
        *,
        recreate: bool = False,
    ) -> IngestStats:
        """Run the full 5-phase ingestion pipeline.

        Args:
            trees:          Parsed RequirementTree objects (from *_tree.json).
            manifest_files: Resolved cross-reference manifest JSON paths.
            recreate:       Drop and recreate all collections before ingesting.
        """
        assert self._client is not None, "Call connect() first"

        stats = IngestStats(trees_loaded=len(trees))
        self.ensure_collections(recreate=recreate)

        # ── Load cross-reference manifests ────────────────────────────────────
        dep_map, std_refs_by_req = self._load_manifests(manifest_files or [], stats)

        # ── Build per-tree lookup maps ─────────────────────────────────────────
        # req_id → (Requirement, RequirementTree) across all trees
        all_reqs: dict[str, tuple[Requirement, RequirementTree]] = {}
        for tree in trees:
            for req in tree.requirements:
                if req.req_id:
                    all_reqs[req.req_id] = (req, tree)
                else:
                    stats.skipped_no_req_id += 1
        stats.total_requirements = len(all_reqs)

        # ── Phase 1: Standards placeholder rows ───────────────────────────────
        logger.info("Phase 1 — inserting Standards placeholder rows")
        std_uuid_by_key: dict[str, str] = {}
        self._phase1_standards(all_reqs, std_refs_by_req, std_uuid_by_key, stats)

        # ── Phase 2: RequirementRelease rows ──────────────────────────────────
        logger.info("Phase 2 — inserting RequirementRelease rows")
        class2_uuid_by_req: dict[str, str] = {}
        self._phase2_req_releases(all_reqs, dep_map, std_refs_by_req, std_uuid_by_key, class2_uuid_by_req, stats)

        # ── Phase 3: Requirement rows ──────────────────────────────────────────
        logger.info("Phase 3 — inserting Requirement rows")
        self._phase3_requirements(all_reqs, std_refs_by_req, std_uuid_by_key, class2_uuid_by_req, stats)

        # ── Phase 4: Update depends_on cross-refs ─────────────────────────────
        logger.info("Phase 4 — updating depends_on cross-references")
        self._phase4_depends_on(dep_map, all_reqs, stats)

        # ── Phase 5: CarrierRelease upsert ────────────────────────────────────
        logger.info("Phase 5 — upserting CarrierRelease rows")
        self._phase5_carrier_release(trees, stats)

        logger.info(
            "Ingestion complete — reqs=%d, releases=%d, standards=%d, "
            "depends_on=%d, errors=%d",
            stats.inserted_requirements,
            stats.inserted_req_releases,
            stats.inserted_standards,
            stats.updated_depends_on,
            stats.errors,
        )
        return stats

    # ── Manifest loading ───────────────────────────────────────────────────────

    def _load_manifests(
        self,
        manifest_files: list[Path],
        stats: IngestStats,
    ) -> tuple[dict[str, list[str]], dict[str, list[dict]]]:
        """Load cross-reference manifests.

        Returns:
          dep_map:         req_id → [target_req_id, ...]  (internal resolved refs)
          std_refs_by_req: req_id → [std_ref_dict, ...]   (standards citations)
        """
        dep_map: dict[str, list[str]] = defaultdict(list)
        std_refs_by_req: dict[str, list[dict]] = defaultdict(list)

        for path in manifest_files:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as exc:
                logger.warning("Failed to load manifest %s: %s", path, exc)
                continue

            stats.manifests_loaded += 1

            # Internal refs — direct req-to-req dependencies (resolved only)
            for ref in data.get("internal_refs", []):
                if ref.get("status") == "resolved":
                    src = ref.get("source_req_id", "")
                    tgt = ref.get("target_req_id", "")
                    if src and tgt and tgt not in dep_map[src]:
                        dep_map[src].append(tgt)

            # Standards refs
            for ref in data.get("standards_refs", []):
                src = ref.get("source_req_id", "")
                if src and ref.get("spec"):
                    std_refs_by_req[src].append(ref)

        logger.info(
            "Manifests: %d files, %d reqs with deps, %d reqs with std refs",
            stats.manifests_loaded,
            len(dep_map),
            len(std_refs_by_req),
        )
        return dict(dep_map), dict(std_refs_by_req)

    # ── Phase 1 — Standards ───────────────────────────────────────────────────

    def _phase1_standards(
        self,
        all_reqs: dict[str, tuple[Requirement, RequirementTree]],
        std_refs_by_req: dict[str, list[dict]],
        std_uuid_by_key: dict[str, str],
        stats: IngestStats,
    ) -> None:
        from weaviate.util import generate_uuid5

        collection = self._client.collections.get(STANDARDS)

        with collection.batch.fixed_size(batch_size=self._batch_size) as batch:
            for req_id, std_refs in std_refs_by_req.items():
                req_tree = all_reqs.get(req_id)
                if not req_tree:
                    continue
                _, tree = req_tree
                carrier = tree.mno or "UNKNOWN"

                for ref in std_refs:
                    spec = ref.get("spec", "")
                    parsed = _parse_spec(spec)
                    if not parsed:
                        continue  # skip OMADM and unknown prefixes
                    standard_type, doc_id = parsed

                    # Determine content_type and content_id
                    section = ref.get("section", "").strip()
                    annex   = ref.get("annex", "").strip()
                    table   = ref.get("table", "").strip()
                    if section:
                        content_type, content_id = "section", section
                    elif annex:
                        content_type, content_id = "annex", annex
                    elif table:
                        content_type, content_id = "table", table
                    else:
                        content_type, content_id = "section", ""  # spec-level ref

                    uuid_key = _standards_uuid_key(carrier, req_id, spec, content_type, content_id)
                    if uuid_key in std_uuid_by_key:
                        continue  # already queued this citation
                    obj_uuid = generate_uuid5(uuid_key)
                    std_uuid_by_key[uuid_key] = obj_uuid

                    batch.add_object(
                        properties={
                            "doc_id":            doc_id,
                            "release_id":        ref.get("release", ""),
                            "standard_type":     standard_type,
                            "content_type":      content_type,
                            "content_id":        content_id,
                            "content_text":      "",    # placeholder — loaded later
                            "content_available": False,
                            "carriers":          [carrier],
                            "req_id":            req_id,
                        },
                        uuid=obj_uuid,
                    )
                    stats.inserted_standards += 1

        self._check_batch_errors(collection, stats)

    # ── Phase 2 — RequirementRelease ─────────────────────────────────────────

    def _phase2_req_releases(
        self,
        all_reqs: dict[str, tuple[Requirement, RequirementTree]],
        dep_map: dict[str, list[str]],
        std_refs_by_req: dict[str, list[dict]],
        std_uuid_by_key: dict[str, str],
        class2_uuid_by_req: dict[str, str],
        stats: IngestStats,
    ) -> None:
        from weaviate.util import generate_uuid5
        import weaviate.classes as wvc

        collection = self._client.collections.get(REQUIREMENT_RELEASE)

        with collection.batch.fixed_size(batch_size=self._batch_size) as batch:
            for req_id, (req, tree) in all_reqs.items():
                carrier = tree.mno or "UNKNOWN"
                release = tree.release or ""

                defs_map = tree.definitions_map or {}
                defs_pat = _compile_definitions_regex(defs_map)

                req_text      = _build_req_text(req, defs_map, defs_pat)
                req_tables    = [_table_to_markdown(t) for t in (req.tables or []) if t]
                req_tables    = [t for t in req_tables if t]  # drop empty
                image_captions = " | ".join(
                    img.surrounding_text for img in (req.images or [])
                    if img.surrounding_text
                )
                has_images = bool(req.images)
                c_hash = _content_hash(req_text, req_tables, image_captions)

                # Class 1 UUID (deterministic — pre-compute for current_req ref)
                class1_uuid = generate_uuid5(f"{carrier}:{req_id}")
                # Class 2 UUID (content-based — same content = same UUID = upsert)
                class2_uuid = generate_uuid5(f"{carrier}:{req_id}:{c_hash}")
                class2_uuid_by_req[req_id] = class2_uuid

                # depends_on_req_ids — resolved internal deps as text array
                dep_req_ids = dep_map.get(req_id, [])

                # Standards cross-refs for this req
                std_refs_for_this = std_refs_by_req.get(req_id, [])
                std_ref_uuids = []
                for ref in std_refs_for_this:
                    spec = ref.get("spec", "")
                    parsed = _parse_spec(spec)
                    if not parsed:
                        continue
                    section  = ref.get("section", "").strip()
                    annex    = ref.get("annex", "").strip()
                    table    = ref.get("table", "").strip()
                    if section:
                        ct, ci = "section", section
                    elif annex:
                        ct, ci = "annex", annex
                    elif table:
                        ct, ci = "table", table
                    else:
                        ct, ci = "section", ""
                    key = _standards_uuid_key(carrier, req_id, spec, ct, ci)
                    u = std_uuid_by_key.get(key)
                    if u:
                        std_ref_uuids.append(u)

                properties = {
                    "req_id":             req_id,
                    "carrier":            carrier,
                    "req_text":           req_text,
                    "req_tables":         req_tables,
                    "req_releases":       [release],
                    "has_images":         has_images,
                    "image_captions":     image_captions,
                    "req_tg":             "",
                    "depends_on_req_ids": dep_req_ids,
                    "content_hash":       c_hash,
                    "parent_req_id":      req.parent_req_id or "",
                    "children_req_ids":   list(req.children or []),
                    "hierarchy_path":     list(req.hierarchy_path or []),
                }

                references = {
                    "current_req": class1_uuid,
                }
                if std_ref_uuids:
                    references["standards"] = std_ref_uuids

                batch.add_object(
                    properties=properties,
                    references=references,
                    uuid=class2_uuid,
                )
                stats.inserted_req_releases += 1

        self._check_batch_errors(collection, stats)

    # ── Phase 3 — Requirement ─────────────────────────────────────────────────

    def _phase3_requirements(
        self,
        all_reqs: dict[str, tuple[Requirement, RequirementTree]],
        std_refs_by_req: dict[str, list[dict]],
        std_uuid_by_key: dict[str, str],
        class2_uuid_by_req: dict[str, str],
        stats: IngestStats,
    ) -> None:
        from weaviate.util import generate_uuid5

        collection = self._client.collections.get(REQUIREMENT)

        with collection.batch.fixed_size(batch_size=self._batch_size) as batch:
            for req_id, (req, tree) in all_reqs.items():
                carrier = tree.mno or "UNKNOWN"
                release = tree.release or ""

                defs_map = tree.definitions_map or {}
                defs_pat = _compile_definitions_regex(defs_map)

                req_text      = _build_req_text(req, defs_map, defs_pat)
                req_tables    = [_table_to_markdown(t) for t in (req.tables or []) if t]
                req_tables    = [t for t in req_tables if t]
                image_captions = " | ".join(
                    img.surrounding_text for img in (req.images or [])
                    if img.surrounding_text
                )

                class1_uuid = generate_uuid5(f"{carrier}:{req_id}")
                class2_uuid = class2_uuid_by_req.get(req_id)

                # Standards cross-refs for this req
                std_refs_for_this = std_refs_by_req.get(req_id, [])
                std_ref_uuids = []
                for ref in std_refs_for_this:
                    spec = ref.get("spec", "")
                    parsed = _parse_spec(spec)
                    if not parsed:
                        continue
                    section  = ref.get("section", "").strip()
                    annex    = ref.get("annex", "").strip()
                    table    = ref.get("table", "").strip()
                    if section:
                        ct, ci = "section", section
                    elif annex:
                        ct, ci = "annex", annex
                    elif table:
                        ct, ci = "table", table
                    else:
                        ct, ci = "section", ""
                    key = _standards_uuid_key(carrier, req_id, spec, ct, ci)
                    u = std_uuid_by_key.get(key)
                    if u:
                        std_ref_uuids.append(u)

                properties = {
                    "req_id":            req_id,
                    "carrier":           carrier,
                    "req_text":          req_text,
                    "req_tables":        req_tables,
                    "req_tg":            "",
                    "has_images":        bool(req.images),
                    "image_captions":    image_captions,
                    "current_release":   release,
                    "parent_req_id":     req.parent_req_id or "",
                    "children_req_ids":  list(req.children or []),
                    "hierarchy_path":    list(req.hierarchy_path or []),
                }

                references: dict[str, Any] = {}
                if class2_uuid:
                    references["release_history"] = [class2_uuid]
                if std_ref_uuids:
                    references["standards"] = std_ref_uuids

                batch.add_object(
                    properties=properties,
                    references=references if references else None,
                    uuid=class1_uuid,
                )
                stats.inserted_requirements += 1

        self._check_batch_errors(collection, stats)

    # ── Phase 4 — depends_on cross-refs ──────────────────────────────────────

    def _phase4_depends_on(
        self,
        dep_map: dict[str, list[str]],
        all_reqs: dict[str, tuple[Requirement, RequirementTree]],
        stats: IngestStats,
    ) -> None:
        """Add self-referential depends_on[] cross-refs to Requirement rows.

        Done in a second pass after all Requirement rows exist (so target
        UUIDs are valid at reference-add time).
        """
        from weaviate.util import generate_uuid5

        collection = self._client.collections.get(REQUIREMENT)
        ref_count = 0

        for req_id, dep_req_ids in dep_map.items():
            req_tree = all_reqs.get(req_id)
            if not req_tree:
                continue
            _, tree = req_tree
            carrier = tree.mno or "UNKNOWN"
            source_uuid = generate_uuid5(f"{carrier}:{req_id}")

            for dep_req_id in dep_req_ids:
                # Only add if target req exists in our corpus
                if dep_req_id not in all_reqs:
                    continue
                _, dep_tree = all_reqs[dep_req_id]
                dep_carrier = dep_tree.mno or "UNKNOWN"
                target_uuid = generate_uuid5(f"{dep_carrier}:{dep_req_id}")

                try:
                    collection.data.reference_add(
                        from_uuid=source_uuid,
                        from_property="depends_on",
                        to=target_uuid,
                    )
                    ref_count += 1
                except Exception as exc:
                    logger.warning(
                        "depends_on ref failed %s → %s: %s", req_id, dep_req_id, exc
                    )
                    stats.errors += 1

        stats.updated_depends_on = ref_count
        logger.info("Phase 4 complete: %d depends_on refs added", ref_count)

    # ── Phase 5 — CarrierRelease ──────────────────────────────────────────────

    def _phase5_carrier_release(
        self,
        trees: list[RequirementTree],
        stats: IngestStats,
    ) -> None:
        """Upsert one CarrierRelease row per carrier."""
        from weaviate.util import generate_uuid5
        import datetime

        # Collect all releases per carrier
        releases_by_carrier: dict[str, set[str]] = defaultdict(set)
        for tree in trees:
            carrier = tree.mno or "UNKNOWN"
            if tree.release:
                releases_by_carrier[carrier].add(tree.release)

        collection = self._client.collections.get(CARRIER_RELEASE)
        now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        with collection.batch.fixed_size(batch_size=self._batch_size) as batch:
            for carrier, releases in releases_by_carrier.items():
                all_releases = sorted(releases)
                latest_release = all_releases[-1] if all_releases else ""
                carrier_uuid = generate_uuid5(carrier)

                batch.add_object(
                    properties={
                        "carrier":            carrier,
                        "latest_release":     latest_release,
                        "all_releases":       all_releases,
                        "latest_fld_release": "",
                        "all_fld_releases":   [],
                        "last_updated":       now_str,
                    },
                    uuid=carrier_uuid,
                )

        self._check_batch_errors(collection, stats)
        logger.info(
            "Phase 5 complete: %d carrier(s) upserted", len(releases_by_carrier)
        )

    # ── Batch error helper ────────────────────────────────────────────────────

    def _check_batch_errors(self, collection, stats: IngestStats) -> None:
        failed = getattr(collection.batch, "failed_objects", None) or []
        for err in failed:
            logger.warning("Batch error: %s", err)
            stats.errors += 1
