"""Weaviate collection schemas for NORA — 6 collections.

Insertion order (cross-reference dependencies must exist before referencing):
  1. Standards          — spec content rows (no inbound refs at insert time)
  2. RequirementRelease — per-release snapshots → refs Standards
  3. Requirement        — latest-release view  → refs RequirementRelease, Standards
  4. DeviceCompliance   — compliance results   → refs Requirement, RequirementRelease
  5. Feature            — FUTURE (schema only, not ingested)
  6. CarrierRelease     — one row per carrier, no cross-refs

Cross-reference graph:
  Requirement.depends_on[]      → Requirement[]         (self-referential)
  Requirement.standards[]       → Standards[]
  Requirement.release_history[] → RequirementRelease[]
  RequirementRelease.standards[]→ Standards[]
  RequirementRelease.current_req→ Requirement
  Standards.release_req_id      → RequirementRelease
  DeviceCompliance.req_release  → RequirementRelease
  DeviceCompliance.requirement  → Requirement
  Feature.req_releases[]        → RequirementRelease[]  (future)
"""

from __future__ import annotations

from typing import Any

# ── Collection name constants ─────────────────────────────────────────────────

REQUIREMENT         = "Requirement"
REQUIREMENT_RELEASE = "RequirementRelease"
STANDARDS           = "Standards"
DEVICE_COMPLIANCE   = "DeviceCompliance"
FEATURE             = "Feature"
CARRIER_RELEASE     = "CarrierRelease"

# Schema creation order — referenced collections must be created before
# collections that hold cross-references to them.
CREATION_ORDER = [
    STANDARDS,
    REQUIREMENT_RELEASE,
    REQUIREMENT,
    DEVICE_COMPLIANCE,
    FEATURE,
    CARRIER_RELEASE,
]


# ── Property helpers ──────────────────────────────────────────────────────────


def _p(name: str, data_type, *, searchable: bool = False, filterable: bool = True):
    """Build a weaviate Property with consistent BM25 / filter settings.

    searchable=True  → BM25 keyword index (full-text content fields).
    searchable=False → metadata / filter field only (IDs, codes, flags).

    skip_vectorization=True always — we use Vectorizer.none() and supply
    vectors manually (or omit them for BM25-only operation).
    """
    import weaviate.classes as wvc  # deferred — not imported at module level
    return wvc.config.Property(
        name=name,
        data_type=data_type,
        skip_vectorization=True,
        index_searchable=searchable,
        index_filterable=filterable,
    )


def _r(name: str, target: str):
    """Build a ReferenceProperty to another collection."""
    import weaviate.classes as wvc
    return wvc.config.ReferenceProperty(name=name, target_collection=target)


# ── Collection schemas ────────────────────────────────────────────────────────


def requirement_schema() -> dict[str, Any]:
    """Class 1 — Requirement (latest release, one row per carrier+req_id).

    UUID: generate_uuid5(carrier + ":" + req_id)
    Vectorized fields: req_text, req_tables, image_captions
    """
    import weaviate.classes as wvc
    D = wvc.config.DataType
    return dict(
        name=REQUIREMENT,
        vectorizer_config=wvc.config.Configure.Vectorizer.none(),
        properties=[
            _p("req_id",           D.TEXT,       searchable=False),
            _p("carrier",          D.TEXT,       searchable=False),
            _p("req_text",         D.TEXT,       searchable=True),    # BM25 + vector
            _p("req_tables",       D.TEXT_ARRAY, searchable=True),    # BM25
            _p("req_tg",           D.TEXT,       searchable=False),
            _p("has_images",       D.BOOL,       searchable=False),
            _p("image_captions",   D.TEXT,       searchable=True),
            _p("current_release",  D.TEXT,       searchable=False),
            _p("parent_req_id",    D.TEXT,       searchable=False),   # context enrichment
            _p("children_req_ids", D.TEXT_ARRAY, searchable=False),   # context enrichment
            _p("hierarchy_path",   D.TEXT_ARRAY, searchable=False),   # breadcrumb display
        ],
        references=[
            _r("depends_on",      REQUIREMENT),            # self-referential
            _r("standards",       STANDARDS),
            _r("release_history", REQUIREMENT_RELEASE),
        ],
    )


def requirement_release_schema() -> dict[str, Any]:
    """Class 2 — RequirementRelease (permanent history per content version).

    UUID: generate_uuid5(carrier + ":" + req_id + ":" + content_hash)
    Same content across releases → UPDATE req_releases[], never re-insert.
    Vectorized fields: req_text, req_tables, image_captions
    """
    import weaviate.classes as wvc
    D = wvc.config.DataType
    return dict(
        name=REQUIREMENT_RELEASE,
        vectorizer_config=wvc.config.Configure.Vectorizer.none(),
        properties=[
            _p("req_id",             D.TEXT,       searchable=False),
            _p("carrier",            D.TEXT,       searchable=False),
            _p("req_text",           D.TEXT,       searchable=True),
            _p("req_tables",         D.TEXT_ARRAY, searchable=True),
            _p("req_releases",       D.TEXT_ARRAY, searchable=False),
            _p("has_images",         D.BOOL,       searchable=False),
            _p("image_captions",     D.TEXT,       searchable=True),
            _p("req_tg",             D.TEXT,       searchable=False),
            _p("depends_on_req_ids", D.TEXT_ARRAY, searchable=False),
            _p("content_hash",       D.TEXT,       searchable=False),
            _p("parent_req_id",      D.TEXT,       searchable=False),   # context enrichment
            _p("children_req_ids",   D.TEXT_ARRAY, searchable=False),   # context enrichment
            _p("hierarchy_path",     D.TEXT_ARRAY, searchable=False),   # breadcrumb display
        ],
        references=[
            _r("standards",    STANDARDS),
            _r("current_req",  REQUIREMENT),
        ],
    )


def standards_schema() -> dict[str, Any]:
    """Class 3 — Standards (one row per citation instance from a requirement).

    UUID: generate_uuid5(carrier + ":" + req_id + ":" + spec + ":" + content_type + ":" + content_id)
    One Standards row per (source_req_id, spec, content_type, content_id) tuple.
    content_available=False for placeholder rows (content loaded separately).
    Vectorized fields: content_text
    """
    import weaviate.classes as wvc
    D = wvc.config.DataType
    return dict(
        name=STANDARDS,
        vectorizer_config=wvc.config.Configure.Vectorizer.none(),
        properties=[
            _p("doc_id",            D.TEXT,       searchable=False),  # e.g. "24.301"
            _p("release_id",        D.TEXT,       searchable=False),  # e.g. "Release 15"
            _p("standard_type",     D.TEXT,       searchable=False),  # "3GPP" | "ETSI"
            _p("content_type",      D.TEXT,       searchable=False),  # "section"|"table"|"annex"
            _p("content_id",        D.TEXT,       searchable=False),  # section/table/annex ref
            _p("content_text",      D.TEXT,       searchable=True),   # BM25 + vector
            _p("content_available", D.BOOL,       searchable=False),  # False = placeholder
            _p("carriers",          D.TEXT_ARRAY, searchable=False),
            _p("req_id",            D.TEXT,       searchable=False),  # source req (direct lookup)
        ],
        references=[
            _r("release_req_id", REQUIREMENT_RELEASE),
        ],
    )


def device_compliance_schema() -> dict[str, Any]:
    """Class 4 — DeviceCompliance (per-device, per-fld-release compliance).

    UUID: generate_uuid5(carrier + ":" + req_id + ":" + model + ":" + fld_release)
    Ingestion source: Excel file per device model (future step).
    Vectorized fields: justification
    """
    import weaviate.classes as wvc
    D = wvc.config.DataType
    return dict(
        name=DEVICE_COMPLIANCE,
        vectorizer_config=wvc.config.Configure.Vectorizer.none(),
        properties=[
            _p("req_id",          D.TEXT, searchable=False),
            _p("carrier",         D.TEXT, searchable=False),
            _p("model",           D.TEXT, searchable=False),
            _p("fld_release",     D.TEXT, searchable=False),
            _p("compliance",      D.TEXT, searchable=False),  # yes/no/n/a/partial
            _p("justification",   D.TEXT, searchable=True),   # BM25 + vector
            _p("req_tg",          D.TEXT, searchable=False),
            _p("tg_owner_corpid", D.TEXT, searchable=False),
            _p("tg_owner_name",   D.TEXT, searchable=False),
            _p("status",          D.TEXT, searchable=False),  # completed/not-completed
            _p("compliance_date", D.DATE, searchable=False),
        ],
        references=[
            _r("req_release",  REQUIREMENT_RELEASE),
            _r("requirement",  REQUIREMENT),
        ],
    )


def feature_schema() -> dict[str, Any]:
    """Class 5 — Feature (FUTURE — schema defined, not yet ingested).

    Deferred until formal feature taxonomy requirements are defined.
    """
    import weaviate.classes as wvc
    D = wvc.config.DataType
    return dict(
        name=FEATURE,
        vectorizer_config=wvc.config.Configure.Vectorizer.none(),
        properties=[
            _p("feature_id",        D.TEXT, searchable=True),
            _p("feature_name",      D.TEXT, searchable=True),
            _p("carrier_vocab_map", D.TEXT, searchable=False),  # JSON string map
        ],
        references=[
            _r("req_releases", REQUIREMENT_RELEASE),
        ],
    )


def carrier_release_schema() -> dict[str, Any]:
    """Class 6 — CarrierRelease (one row per carrier, no cross-refs).

    UUID: generate_uuid5(carrier)
    Updated on each quarterly ingestion and compliance Excel import.
    """
    import weaviate.classes as wvc
    D = wvc.config.DataType
    return dict(
        name=CARRIER_RELEASE,
        vectorizer_config=wvc.config.Configure.Vectorizer.none(),
        properties=[
            _p("carrier",            D.TEXT,       searchable=False),
            _p("latest_release",     D.TEXT,       searchable=False),
            _p("all_releases",       D.TEXT_ARRAY, searchable=False),
            _p("latest_fld_release", D.TEXT,       searchable=False),
            _p("all_fld_releases",   D.TEXT_ARRAY, searchable=False),
            _p("release_date",       D.DATE,       searchable=False),
            _p("fld_release_date",   D.DATE,       searchable=False),
            _p("last_updated",       D.DATE,       searchable=False),
        ],
        # No cross-references
    )


# ── Schema registry ───────────────────────────────────────────────────────────

# Ordered dict — creation order respected
SCHEMAS: dict[str, Any] = {
    STANDARDS:           standards_schema,
    REQUIREMENT_RELEASE: requirement_release_schema,
    REQUIREMENT:         requirement_schema,
    DEVICE_COMPLIANCE:   device_compliance_schema,
    FEATURE:             feature_schema,
    CARRIER_RELEASE:     carrier_release_schema,
}
