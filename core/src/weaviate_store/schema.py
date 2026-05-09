"""Weaviate collection schema and object model for NORA requirements."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

COLLECTION_NAME = "Requirement"


@dataclass
class RequirementObject:
    """Flat representation of a single requirement for Weaviate storage.

    Combines fields from Requirement + RequirementTree (provenance) plus
    resolved cross-reference IDs from CrossReferenceManifest.
    """

    # Requirement identity
    req_id: str
    plan_id: str
    mno: str
    release: str
    plan_name: str

    # Structural location
    section_number: str
    title: str
    parent_req_id: str
    parent_section: str
    hierarchy_path: list[str] = field(default_factory=list)

    # Requirement content
    zone_type: str = ""
    priority: str = ""
    applicability: list[str] = field(default_factory=list)
    text: str = ""

    # Resolved cross-references (populated by resolver)
    internal_ref_ids: list[str] = field(default_factory=list)
    cross_plan_ids: list[str] = field(default_factory=list)
    standards_specs: list[str] = field(default_factory=list)

    def uuid_key(self) -> str:
        """Stable string used to derive the deterministic UUID."""
        if self.req_id:
            return self.req_id
        return f"{self.plan_id}::{self.section_number}::{self.title[:40]}"

    def to_properties(self) -> dict[str, Any]:
        return {
            "req_id": self.req_id,
            "plan_id": self.plan_id,
            "mno": self.mno,
            "release": self.release,
            "plan_name": self.plan_name,
            "section_number": self.section_number,
            "title": self.title,
            "parent_req_id": self.parent_req_id,
            "parent_section": self.parent_section,
            "hierarchy_path": self.hierarchy_path,
            "zone_type": self.zone_type,
            "priority": self.priority,
            "applicability": self.applicability,
            "text": self.text,
            "internal_ref_ids": self.internal_ref_ids,
            "cross_plan_ids": self.cross_plan_ids,
            "standards_specs": self.standards_specs,
        }


def collection_schema() -> dict[str, Any]:
    """Return kwargs for client.collections.create() using weaviate-client v4."""
    try:
        import weaviate.classes as wvc
    except ImportError as exc:
        raise ImportError("weaviate-client>=4.0.0 required: pip install weaviate-client") from exc

    return {
        "name": COLLECTION_NAME,
        "vectorizer_config": wvc.config.Configure.Vectorizer.none(),
        "properties": [
            wvc.config.Property(name="req_id", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="plan_id", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="mno", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="release", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="plan_name", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="section_number", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="title", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="parent_req_id", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="parent_section", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(
                name="hierarchy_path", data_type=wvc.config.DataType.TEXT_ARRAY
            ),
            wvc.config.Property(name="zone_type", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="priority", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(
                name="applicability", data_type=wvc.config.DataType.TEXT_ARRAY
            ),
            wvc.config.Property(name="text", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(
                name="internal_ref_ids", data_type=wvc.config.DataType.TEXT_ARRAY
            ),
            wvc.config.Property(
                name="cross_plan_ids", data_type=wvc.config.DataType.TEXT_ARRAY
            ),
            wvc.config.Property(
                name="standards_specs", data_type=wvc.config.DataType.TEXT_ARRAY
            ),
        ],
    }
