"""Dataclasses passed between profile_miner sub-modules."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class EnrichedCorrection:
    """One correction joined to its source block and ±N neighbours.

    Built by ``loader.load_corrections`` from the on-disk
    ``<env_dir>/corrections/<doc_id>_corrections.json`` entries + the
    matching IR. The miner consumes a list of these.
    """

    doc_id: str
    kind: str  # "missed" | "false_positive"
    expected_reason: str  # e.g. "dropped_revhist", "glossary", "reference_spec"
    block_idx: int
    pages: str
    block_text: str  # full block text from IR
    block_type: str = ""  # "heading" | "paragraph" | "table" | "image"; from IR
    table_headers: list[str] = field(default_factory=list)
    """For table blocks: the column headers. The miner uses these
    directly when emitting a *_table_header_pattern proposal — the
    regex will be tested against ' | '.join(headers) at parse time."""
    neighbour_texts: list[str] = field(default_factory=list)
    comment: str = ""  # user rationale, optional


@dataclass
class ProfileFieldPatch:
    """One proposed pattern (or list of patterns) for a single profile field.

    Multiple examples that cluster under one ``expected_reason`` collapse
    into one ``ProfileFieldPatch`` so the human reviewer sees one regex
    per concept rather than one per correction.
    """

    profile_field: str  # dotted path, e.g. "heading_detection.definitions_section_pattern"
    list_field: bool  # True if profile_field is list[str]; pattern is appended not replaced
    expected_reason: str
    proposed_pattern: str
    rationale: str  # LLM's plain-English justification
    confidence: float  # LLM-self-reported [0.0, 1.0]
    example_block_idxs: list[int] = field(default_factory=list)
    example_previews: list[str] = field(default_factory=list)


@dataclass
class ProfilePatch:
    """Aggregate output for one document. Emitted to
    ``<env_dir>/reports/profile_patch_<doc_id>.json``."""

    doc_id: str
    generated_at: str
    field_patches: list[ProfileFieldPatch] = field(default_factory=list)
    unmapped: list[ProfileFieldPatch] = field(default_factory=list)
    """Patches whose ``expected_reason`` has no canonical profile field
    yet — surfaced separately so the reviewer can decide where they go."""

    def save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
