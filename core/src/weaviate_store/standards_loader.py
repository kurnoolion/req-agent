"""Load parsed spec content into Weaviate Standards placeholder rows.

Reads every data/standards/TS_<doc_id>/Rel-<N>/spec_parsed.json file and
updates matching placeholder Standards rows (content_available=False) with
the extracted section text, then flips content_available=True.

Directory layout expected:
    data/standards/
        TS_23.503/
            Rel-15/
                spec_parsed.json   ← sections list
                sections.json      ← metadata index (not used by loader)
        TS_38.101/
            Rel-16/
                spec_parsed.json
        ...

Matching strategy by content_type:
    section  content_id="4.2.1"      → section_map["4.2.1"]          (direct)
    table    content_id="5.3A.2-2"   → section_map["5.3A.2"]         (strip -N suffix)
    table    content_id="4.1-1"      → section_map["4.1"]
    table    content_id="5.2D-1"     → section_map["5.2D"]
    annex    content_id="A.3.3.1.2"  → section_map["A.3.3.1.2"]      (direct)

Rows where the section/annex text is not found in spec_parsed.json are
left as content_available=False (logged as 'not_found').
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Folder name helpers ───────────────────────────────────────────────────────


def _folder_to_doc_id(folder_name: str) -> str:
    """Convert spec folder name to doc_id.

    'TS_23.503' → '23.503'
    'TR_38.913' → '38.913'
    'EN_301.511' → '301.511'
    """
    for prefix in ("TS_", "TR_", "EN_", "ES_"):
        if folder_name.startswith(prefix):
            return folder_name[len(prefix):]
    return folder_name


def _rel_folder_to_release_id(rel_folder: str) -> str:
    """Convert release subfolder name to release_id string.

    'Rel-15' → 'Release 15'
    'Rel-9'  → 'Release 9'
    """
    if rel_folder.startswith("Rel-"):
        return f"Release {rel_folder[4:]}"
    return rel_folder


# ── Section map builder ───────────────────────────────────────────────────────


def _build_section_map(sections: list[dict]) -> dict[str, str]:
    """Return {section_number: text} for all sections with non-empty content.

    Sections with blank number (e.g. Foreword) or blank text are excluded.
    """
    mapping: dict[str, str] = {}
    for s in sections:
        num  = (s.get("number") or "").strip()
        text = (s.get("text")   or "").strip()
        if num and text:
            mapping[num] = text
    return mapping


# ── Content lookup ────────────────────────────────────────────────────────────


def _lookup_text(
    content_type: str,
    content_id: str,
    section_map: dict[str, str],
) -> str | None:
    """Find the text for a Standards row given its content_type and content_id.

    section / annex → direct lookup by content_id.
    table           → strip trailing -<digits> suffix to get parent section,
                      then look up that section's text.

    Returns None when no matching section is found.
    """
    if content_type in ("section", "annex"):
        return section_map.get(content_id)

    if content_type == "table":
        # Examples:
        #   "4.1-1"      → base "4.1"
        #   "5.2D-1"     → base "5.2D"
        #   "5.3A.2-2"   → base "5.3A.2"
        #   "6.2A.2.4-1" → base "6.2A.2.4"
        #   "5.3.3-2"    → base "5.3.3"
        if "-" in content_id:
            base = content_id.rsplit("-", 1)[0]
            return section_map.get(base)
        # No hyphen — treat as section fallback
        return section_map.get(content_id)

    # Unknown content_type — try direct match
    return section_map.get(content_id)


# ── Stats ─────────────────────────────────────────────────────────────────────


@dataclass
class LoaderStats:
    specs_processed:   int = 0
    rows_found:        int = 0
    rows_updated:      int = 0
    rows_already_loaded: int = 0
    section_not_found: int = 0
    errors:            int = 0
    skipped_specs:     list[str] = field(default_factory=list)


# ── Loader ────────────────────────────────────────────────────────────────────


class StandardsLoader:
    """Load parsed spec content into Weaviate Standards placeholder rows.

    Usage:
        with weaviate.connect_to_local() as client:
            loader = StandardsLoader(client)
            stats = loader.load(Path("data/standards"))
    """

    def __init__(self, client) -> None:
        self._client = client

    def load(self, standards_dir: Path) -> LoaderStats:
        """Walk standards_dir and update all matching placeholder Standards rows.

        Args:
            standards_dir: Root directory containing TS_*/Rel-*/spec_parsed.json.

        Returns:
            LoaderStats with counts for every outcome.
        """
        try:
            import weaviate.classes as wvc
        except ImportError as exc:
            raise ImportError(
                "weaviate-client>=4.0.0 required: pip install weaviate-client"
            ) from exc

        stats = LoaderStats()
        collection = self._client.collections.get("Standards")

        # Discover all spec_parsed.json files — TS_* or TR_* top-level folders
        spec_files = sorted(standards_dir.glob("*/*/spec_parsed.json"))
        if not spec_files:
            logger.warning("No spec_parsed.json files found under %s", standards_dir)
            return stats

        logger.info("Found %d spec_parsed.json file(s) to process", len(spec_files))

        for spec_file in spec_files:
            rel_folder = spec_file.parent.name        # e.g. "Rel-15"
            ts_folder  = spec_file.parent.parent.name # e.g. "TS_23.503"

            doc_id     = _folder_to_doc_id(ts_folder)
            release_id = _rel_folder_to_release_id(rel_folder)

            try:
                self._load_one_spec(
                    spec_file=spec_file,
                    doc_id=doc_id,
                    release_id=release_id,
                    collection=collection,
                    wvc=wvc,
                    stats=stats,
                )
                stats.specs_processed += 1
            except Exception as exc:
                logger.error(
                    "Error processing %s (%s %s): %s",
                    spec_file, doc_id, release_id, exc,
                )
                stats.errors += 1
                stats.skipped_specs.append(f"{doc_id} {release_id}")

        return stats

    # ── Single-spec processing ────────────────────────────────────────────────

    def _load_one_spec(
        self,
        spec_file: Path,
        doc_id: str,
        release_id: str,
        collection,
        wvc,
        stats: LoaderStats,
    ) -> None:
        # Parse spec_parsed.json
        data = json.loads(spec_file.read_text(encoding="utf-8"))
        sections = data.get("sections", [])
        section_map = _build_section_map(sections)

        logger.debug(
            "%s  %s — %d section(s) in map",
            doc_id, release_id, len(section_map),
        )

        if not section_map:
            logger.warning(
                "%s  %s — spec_parsed.json has no usable sections, skipping",
                doc_id, release_id,
            )
            return

        # Query Weaviate: all Standards rows for this spec + release
        filters = (
            wvc.query.Filter.by_property("doc_id").equal(doc_id) &
            wvc.query.Filter.by_property("release_id").equal(release_id)
        )
        result = collection.query.fetch_objects(
            filters=filters,
            limit=10_000,
            return_properties=["content_type", "content_id", "content_available"],
        )

        rows = result.objects
        stats.rows_found += len(rows)

        updated   = 0
        not_found = 0
        already   = 0

        for obj in rows:
            props = obj.properties

            if props.get("content_available"):
                already += 1
                continue

            content_type = props.get("content_type", "section")
            content_id   = props.get("content_id", "")

            text = _lookup_text(content_type, content_id, section_map)

            if not text:
                not_found += 1
                logger.debug(
                    "No text: %s  %s  type=%s  id=%s",
                    doc_id, release_id, content_type, content_id,
                )
                continue

            collection.data.update(
                uuid=obj.uuid,
                properties={
                    "content_text":      text,
                    "content_available": True,
                },
            )
            updated += 1

        stats.rows_updated        += updated
        stats.rows_already_loaded += already
        stats.section_not_found   += not_found

        logger.info(
            "%-10s  %-12s  rows=%-4d  updated=%-4d  not_found=%-4d  already=%d",
            doc_id, release_id, len(rows), updated, not_found, already,
        )
