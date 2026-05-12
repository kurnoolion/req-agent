"""Per-doc + corpus-level parse summary — debugging companion to the
parse log.

The parse_log records *what* the parser did (which blocks dropped,
which acronyms extracted). The parse_summary records *what evidence
the parser found* for each profile-driven detection (revhist label,
glossary heading, TOC entries). The two layers complement each other:

* ``parse_log.json`` — per-doc audit trail. Engineer-facing.
* ``parse_summary.json`` — corpus rollup with per-doc rows. Architect-
  facing; surfaces ``revhist_sections=0`` / ``glossary_sections=0``
  rows that need profile-rule extension.

Pipeline-stage hook: the parse stage gathers ``RequirementTree.parse_summary``
from every tree and writes a consolidated ``corpus_summary`` to
``<env_dir>/reports/parse_summary.json``. The web Parse Review page
exposes a Summary tab that renders this file as a sortable table.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RevhistMatch:
    """Evidence of a successful revhist detection.

    All optional — a doc may have a label without a table (free-form
    "Changes since v1" prose) or vice versa. ``label_block_index`` is
    the absolute IR index of the label paragraph/heading; the table
    sits at the next non-paragraph block.
    """

    pattern_id: str = ""
    """Identifier of the profile pattern that matched. Currently always
    ``"configured"`` — the active value of
    ``profile.revision_history_label_pattern``. Reserved for multi-pattern
    futures where the user might run several candidate regexes."""

    matched_text: str = ""
    """The runs-aware title text that matched the pattern (i.e., the
    label string sans any trailing req_id run). e.g.
    ``"REVISION HISTORY"`` after the trailing
    ``<MNO0>_REQ_<PLAN0>_1234`` run is stripped."""

    label_block_index: int = -1
    """Absolute IR block index of the label. ``-1`` when no label
    matched."""

    table_headers: list[str] = field(default_factory=list)
    """Column headers of the table that follows the label (if any).
    Useful for designing column-aware filters when extending the
    revhist detector."""


@dataclass
class GlossaryMatch:
    """Evidence of a successful glossary / definitions detection."""

    pattern_id: str = ""
    """Active value of ``heading_detection.definitions_section_pattern``
    when matched."""

    matched_heading: str = ""
    """The section title that triggered the match — e.g.
    ``"GLOSSARY/DEFINITIONS/ACRONYMS"``."""

    table_headers: list[str] = field(default_factory=list)
    """Column headers of the term/definition table (typically
    ``["Acronym/ Term", "Definition"]``). Empty when the glossary is
    body-text-only (paragraph-line layout)."""

    entries_extracted: int = 0
    """Number of ``term -> expansion`` pairs that landed in
    ``RequirementTree.definitions_map``."""


@dataclass
class DocSummary:
    """One row per parsed doc — the unit the Summary tab renders.

    Fields are chosen to make ``revhist_sections=0`` /
    ``glossary_sections=0`` rows obvious when sorted. ``*_match``
    blocks are ``None`` for the missed cases so the UI can show a
    visual placeholder.
    """

    plan_name: str = ""
    plan_id: str = ""
    doc_id: str = ""
    source_file: str = ""
    toc_entries: int = 0
    revhist_sections: int = 0
    revhist_match: RevhistMatch | None = None
    glossary_sections: int = 0
    glossary_match: GlossaryMatch | None = None
    format_errors: dict[str, int] = field(default_factory=dict)
    """Aggregate of per-doc ``parser.format_error`` counts from
    ``ParseLog.toc_pair_misses`` + the inline format-error logs.
    Keys: ``toc_pair_miss``, ``empty_runs_heading``,
    ``concatenated_run_heading``."""


@dataclass
class CorpusSummary:
    """Top-of-file rollup. Read first by the UI to highlight the
    "N of M docs missing revhist" diagnostic line."""

    generated_at: str = ""
    total_docs: int = 0
    docs_without_revhist: int = 0
    docs_without_glossary: int = 0
    docs: list[DocSummary] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load_json(cls, path: Path) -> CorpusSummary:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        docs = []
        for d in data.get("docs", []):
            rh = d.get("revhist_match")
            gl = d.get("glossary_match")
            docs.append(DocSummary(
                plan_name=d.get("plan_name", ""),
                plan_id=d.get("plan_id", ""),
                doc_id=d.get("doc_id", ""),
                source_file=d.get("source_file", ""),
                toc_entries=int(d.get("toc_entries", 0)),
                revhist_sections=int(d.get("revhist_sections", 0)),
                revhist_match=RevhistMatch(**rh) if rh else None,
                glossary_sections=int(d.get("glossary_sections", 0)),
                glossary_match=GlossaryMatch(**gl) if gl else None,
                format_errors=dict(d.get("format_errors", {}) or {}),
            ))
        return cls(
            generated_at=data.get("generated_at", ""),
            total_docs=int(data.get("total_docs", 0)),
            docs_without_revhist=int(data.get("docs_without_revhist", 0)),
            docs_without_glossary=int(data.get("docs_without_glossary", 0)),
            docs=docs,
        )


def build_corpus_summary(
    per_doc: list[DocSummary], generated_at: str = ""
) -> CorpusSummary:
    """Aggregate per-doc summaries into a CorpusSummary.

    ``docs_without_*`` are quick stats the UI surfaces as a top-of-page
    banner; they're derived (not stored) so adding new detector
    counters later doesn't require a schema migration.
    """
    return CorpusSummary(
        generated_at=generated_at,
        total_docs=len(per_doc),
        docs_without_revhist=sum(1 for d in per_doc if d.revhist_sections == 0),
        docs_without_glossary=sum(1 for d in per_doc if d.glossary_sections == 0),
        docs=list(per_doc),
    )
