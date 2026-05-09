"""Style-driven parser for DOCX-origin DocumentIR — no profile required.

Heading hierarchy is derived from Word heading levels already stamped on
ContentBlock by DOCXExtractor (block.type == HEADING, block.level == N).
VZ_REQ_ IDs are split from heading text.  Produces the same RequirementTree
as GenericStructuralParser so downstream stages are unaffected.

Use via parse_cli --no-profile, or instantiate StyleDrivenParser() directly.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from core.src.models.document import BlockType, DocumentIR
from core.src.parser.structural_parser import (
    CrossReferences,
    DocStandardRef,
    ImageRef,
    ParseStats,
    Requirement,
    RequirementTree,
    StandardsRef,
    TableData,
)

logger = logging.getLogger(__name__)

# ── Patterns ─────────────────────────────────────────────────────────

_VZ_REQ_RE = re.compile(r"VZ_REQ_[A-Z0-9_]+(?:\s[A-Z0-9]+)?_\d+")

_META_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("plan_name",    re.compile(r"^Plan\s+Name:\s*(.+)$",      re.IGNORECASE)),
    ("plan_id",      re.compile(r"^Plan\s+Id:\s*(.+)$",        re.IGNORECASE)),
    ("version",      re.compile(r"^Version\s+Number:\s*(.+)$", re.IGNORECASE)),
    ("release_date", re.compile(r"^Release\s+Date:\s*(.+)$",   re.IGNORECASE)),
]

# ── Standards extraction constants ────────────────────────────────────────────

# Spec number: allows internal spaces ("38. 322") and hyphen suffix ("38.101-1")
_SPEC_NUM = r"\d+\.\s*\d+(?:\s*-\s*\d+)?"

# Spec prefix variants — all normalised to "3GPP TS" in output
_SPEC_PFX = r"(?:3GPP\s+(?:TS|TR)|TS|TR)"

# Section number: multi-level dotted (e.g. 5.1.1, 4.2.7.10)
_SEC_NUM = r"\d+(?:\.\d+)+"

# Annex identifier: capital letter with optional .N (e.g. A, L.1, J)
_ANNEX_ID = r"[A-Z](?:\.\d+)?"

# Section list: comma/slash/space-separated numbers with optional "and/or" tail
# e.g. "5.3.1, 5.3.2, 5.4.1, and 5.4.2" or "4.2.7.10/4.2.7.2/4.2.7.14"
_SECS_LIST = (
    r"[\d.,/]+(?:\s+[\d.,/]+)*"
    r"(?:\s+(?:and|or)\s+[\d.,/]+)?"
)

# ── Compound patterns (most-specific → least-specific) ────────────────────────

# Table X.Y-Z in SPEC
_PAT_TABLE = re.compile(
    rf"[Tt]able\s+([\w./\-]+)\s+in\s+(?:{_SPEC_PFX})\s+({_SPEC_NUM})"
)

# Annex X of SPEC
_PAT_ANNEX_OF = re.compile(
    rf"[Aa]nnex\s+({_ANNEX_ID})\s+of\s+(?:{_SPEC_PFX})\s+({_SPEC_NUM})"
)

# Section X of vN.M.P [...] of SPEC (version string encodes release)
_PAT_SEC_VER_OF = re.compile(
    rf"[Ss]ection\s+({_SEC_NUM})\s+of\s+v(\d+)\.\d+\.\d+[^.]*?of\s+(?:{_SPEC_PFX})\s+({_SPEC_NUM})"
)

# Section(s) X,Y,Z of SPEC (plain list — runs after _PAT_SEC_VER_OF)
_PAT_SECS_OF = re.compile(
    rf"[Ss]ections?\s+({_SECS_LIST})\s+of\s+(?:{_SPEC_PFX})\s+({_SPEC_NUM})"
)

# 3GPP Release N version of SPEC
_PAT_REL_OF = re.compile(
    rf"3GPP\s+[Rr]elease\s+(\d+)\s+version\s+of\s+(?:{_SPEC_PFX})\s+({_SPEC_NUM})"
)

# SPEC [specification] Annex X
_PAT_SPEC_ANNEX = re.compile(
    rf"(?:{_SPEC_PFX})\s+({_SPEC_NUM})\s+(?:specification\s+)?[Aa]nnex\s+({_ANNEX_ID})"
)

# SPEC section(s) X,Y
_PAT_SPEC_SECS = re.compile(
    rf"(?:{_SPEC_PFX})\s+({_SPEC_NUM})\s+[Ss]ections?\s+({_SECS_LIST})"
)

# SPEC standalone (fallback — lowest priority)
_PAT_SPEC_ONLY = re.compile(
    rf"(?:{_SPEC_PFX})\s+({_SPEC_NUM})"
)

# Release number in context window
_STD_RELEASE_RE = re.compile(r"[Rr]elease\s+(\d+)")
# Version string release (e.g. v15.6.0 → Release 15)
_VERSION_RELEASE_RE = re.compile(r"\bv(\d+)\.\d+")

# OMA DM
_OMA_RE = re.compile(r"(?:OMADM|OMA\s+DM)\s+[\d.]+")
_OMA_SECTION_RE = re.compile(r"[Ss]ection\s+([\d.]+)")
_CONTEXT_WINDOW = 200


# ── Parser ────────────────────────────────────────────────────────────


class StyleDrivenParser:
    """Parse a DOCX-origin DocumentIR using heading styles; no profile needed.

    Heading levels come from ContentBlock.level (set by DOCXExtractor from
    Word heading styles).  VZ_REQ_ IDs are split from heading text at the
    first occurrence of the VZ_REQ_ marker.  Metadata (plan_name, plan_id,
    version, release_date) is scraped from pre-heading paragraphs via fixed
    label patterns identical to those used in the standalone JSON_parser_tree
    pipeline.
    """

    def parse(self, doc: DocumentIR) -> RequirementTree:
        logger.info("Style-driven parse: %s", doc.source_file)

        meta: dict[str, str] = {
            "plan_name": "", "plan_id": "", "version": "", "release_date": ""
        }

        # Section counter: counters[level] = current count at that level (1-based)
        counters: dict[int, int] = {}
        # Heading stack: (level, req_id, section_number, title)
        heading_stack: list[tuple[int, str, str, str]] = []
        # Nodes by req_id for child appending
        nodes: dict[str, Requirement] = {}
        requirements: list[Requirement] = []
        current: Optional[Requirement] = None
        in_heading_phase = False

        for block in doc.content_blocks:

            if block.type == BlockType.HEADING:
                in_heading_phase = True
                text = (block.text or "").strip()
                level = block.level
                if not text or level is None:
                    continue

                title, req_id = _split_heading(text)
                if req_id is None:
                    logger.debug("Heading has no VZ_REQ_ — skipped: %r", text)
                    continue

                # Update section counters
                counters[level] = counters.get(level, 0) + 1
                for deeper in list(counters):
                    if deeper > level:
                        counters[deeper] = 0
                section_number = ".".join(
                    str(counters.get(lv, 0)) for lv in range(1, level + 1)
                )

                # Update heading stack
                heading_stack = [e for e in heading_stack if e[0] < level]
                heading_stack.append((level, req_id, section_number, title))

                parent_entry = next(
                    (e for e in reversed(heading_stack[:-1]) if e[0] == level - 1),
                    None,
                )
                parent_req_id  = parent_entry[1] if parent_entry else ""
                parent_section = parent_entry[2] if parent_entry else ""
                hierarchy_path = [e[3] for e in heading_stack]
                zone_type = next(
                    (e[3] for e in heading_stack if e[0] == 1), title
                )

                node = Requirement(
                    req_id=req_id,
                    section_number=section_number,
                    title=title,
                    parent_req_id=parent_req_id,
                    parent_section=parent_section,
                    hierarchy_path=hierarchy_path,
                    zone_type=zone_type,
                )
                if parent_req_id and parent_req_id in nodes:
                    nodes[parent_req_id].children.append(req_id)
                nodes[req_id] = node
                requirements.append(node)
                current = node

            elif block.type == BlockType.PARAGRAPH:
                text = (block.text or "").strip()
                if not text:
                    continue

                if not in_heading_phase:
                    _try_extract_metadata(text, meta)
                    continue

                if current is None:
                    continue

                current.text = (
                    current.text + "\n" + text if current.text else text
                )

            elif block.type == BlockType.TABLE:
                if current is not None:
                    current.tables.append(TableData(
                        headers=block.headers or [],
                        rows=block.rows or [],
                        source="inline",
                    ))

            elif block.type == BlockType.IMAGE:
                if current is not None:
                    current.images.append(ImageRef(
                        path=block.image_path or "",
                        surrounding_text=block.surrounding_text or "",
                    ))

        # Extract cross-references for each requirement
        for req in requirements:
            req.cross_references = _extract_cross_refs(req.text)

        # Build doc-level standards list: one DocStandardRef per unique
        # (req_id, spec, section, annex, table, release) tuple.
        seen_keys: set[tuple] = set()
        doc_std_refs: list[DocStandardRef] = []
        for req in requirements:
            for std_ref in req.cross_references.standards:
                if not std_ref.spec:
                    continue
                key = (req.req_id, std_ref.spec, std_ref.section, std_ref.annex, std_ref.table, std_ref.release)
                if key not in seen_keys:
                    seen_keys.add(key)
                    doc_std_refs.append(DocStandardRef(
                        req_id=req.req_id,
                        spec=std_ref.spec,
                        section=std_ref.section,
                        release=std_ref.release,
                        annex=std_ref.annex,
                        table=std_ref.table,
                    ))

        tree = RequirementTree(
            mno=doc.mno,
            release=doc.release,
            plan_id=meta["plan_id"],
            plan_name=meta["plan_name"],
            version=meta["version"],
            release_date=meta["release_date"],
            referenced_standards_releases=doc_std_refs,
            requirements=requirements,
            parse_stats=ParseStats(),
        )
        logger.info(
            "Style-driven parse done: %s requirements, plan_id=%s",
            len(requirements), tree.plan_id,
        )
        return tree


# ── Helpers (module-level, no parser state needed) ────────────────────


def _split_heading(text: str) -> tuple[str, Optional[str]]:
    """Split 'Title VZ_REQ_PLAN_123' → ('Title', 'VZ_REQ_PLAN_123').

    Returns (text, None) if no VZ_REQ_ token is found.
    """
    if "VZ_REQ_" not in text:
        return text, None
    parts = text.split("VZ_REQ_", 1)
    title  = parts[0].strip()
    req_id = ("VZ_REQ_" + parts[1]).strip()
    return title, req_id


def _try_extract_metadata(text: str, meta: dict[str, str]) -> None:
    for field_name, pattern in _META_PATTERNS:
        m = pattern.match(text)
        if m:
            meta[field_name] = m.group(1).strip()
            return


_WHITESPACE_RE = re.compile(r"\s+")


def _norm_spec(num_raw: str) -> str:
    """Normalise a raw spec number to canonical '3GPP TS X.Y[-Z]' form."""
    return "3GPP TS " + _WHITESPACE_RE.sub("", num_raw)


def _parse_secs(raw: str) -> list[str]:
    """Extract individual section numbers from a list string."""
    return re.findall(r"\d+(?:\.\d+)+", raw)


def _find_release(ctx: str) -> str:
    """Return the first release found in a context string, else ''."""
    m = _STD_RELEASE_RE.search(ctx)
    if m:
        return f"Release {m.group(1)}"
    m = _VERSION_RELEASE_RE.search(ctx)
    if m:
        return f"Release {m.group(1)}"
    return ""


def _extract_standards_refs(text: str) -> list[StandardsRef]:
    """Extract all standards references from requirement text.

    Patterns are tried most-specific first.  Each compound match claims
    the positions of the contained spec tokens so the fallback
    (_PAT_SPEC_ONLY) does not double-emit them.
    """
    if not text:
        return []

    refs: list[StandardsRef] = []
    claimed: set[int] = set()   # start positions of spec matches already handled

    def _claim(m_start: int, m_end: int) -> None:
        """Mark every _PAT_SPEC_ONLY hit inside [m_start, m_end] as claimed."""
        for sm in _PAT_SPEC_ONLY.finditer(text, m_start, m_end):
            claimed.add(sm.start())

    def _ctx(m_start: int, m_end: int) -> str:
        return text[max(0, m_start - 100): min(len(text), m_end + 100)]

    # 1. Table X in SPEC
    for m in _PAT_TABLE.finditer(text):
        refs.append(StandardsRef(spec=_norm_spec(m.group(2)), table=m.group(1).strip()))
        _claim(m.start(), m.end())

    # 2. Annex X of SPEC
    for m in _PAT_ANNEX_OF.finditer(text):
        refs.append(StandardsRef(spec=_norm_spec(m.group(2)), annex=m.group(1)))
        _claim(m.start(), m.end())

    # 3. Section X of vN.M.P [...] of SPEC  (version string encodes release)
    for m in _PAT_SEC_VER_OF.finditer(text):
        refs.append(StandardsRef(
            spec=_norm_spec(m.group(3)),
            section=m.group(1),
            release=f"Release {m.group(2)}",
        ))
        _claim(m.start(), m.end())

    # 4. Section(s) X,Y,Z of SPEC
    for m in _PAT_SECS_OF.finditer(text):
        spec = _norm_spec(m.group(2))
        release = _find_release(_ctx(m.start(), m.end()))
        secs = _parse_secs(m.group(1))
        for sec in secs:
            refs.append(StandardsRef(spec=spec, section=sec, release=release))
        if not secs:
            refs.append(StandardsRef(spec=spec, release=release))
        _claim(m.start(), m.end())

    # 5. 3GPP Release N version of SPEC
    for m in _PAT_REL_OF.finditer(text):
        refs.append(StandardsRef(
            spec=_norm_spec(m.group(2)),
            release=f"Release {m.group(1)}",
        ))
        _claim(m.start(), m.end())

    # 6. SPEC [specification] Annex X
    for m in _PAT_SPEC_ANNEX.finditer(text):
        refs.append(StandardsRef(spec=_norm_spec(m.group(1)), annex=m.group(2)))
        _claim(m.start(), m.end())

    # 7. SPEC section(s) X,Y
    for m in _PAT_SPEC_SECS.finditer(text):
        spec = _norm_spec(m.group(1))
        release = _find_release(_ctx(m.start(), m.end()))
        secs = _parse_secs(m.group(2))
        for sec in secs:
            refs.append(StandardsRef(spec=spec, section=sec, release=release))
        if not secs:
            refs.append(StandardsRef(spec=spec, release=release))
        _claim(m.start(), m.end())

    # 8. OMA DM references (separate spec space — no position claiming needed)
    for m in _OMA_RE.finditer(text):
        raw = m.group()
        spec = re.sub(r"OMA\s+DM", "OMADM", raw)
        spec = re.sub(r"\s+", " ", spec).strip()
        win = text[max(0, m.start() - _CONTEXT_WINDOW): min(len(text), m.end() + _CONTEXT_WINDOW)]
        sec_m = _OMA_SECTION_RE.search(win)
        rel_m = _STD_RELEASE_RE.search(win)
        refs.append(StandardsRef(
            spec=spec,
            section=sec_m.group(1) if sec_m else "",
            release=f"Release {rel_m.group(1)}" if rel_m else "",
        ))

    # 9. SPEC standalone (fallback — skip positions claimed by compound patterns)
    for m in _PAT_SPEC_ONLY.finditer(text):
        if m.start() in claimed:
            continue
        refs.append(StandardsRef(
            spec=_norm_spec(m.group(1)),
            release=_find_release(_ctx(m.start(), m.end())),
        ))

    # Deduplicate preserving first-occurrence order
    seen: set[tuple] = set()
    unique: list[StandardsRef] = []
    for r in refs:
        key = (r.spec, r.section, r.annex, r.table, r.release)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def _extract_cross_refs(text: str) -> CrossReferences:
    if not text:
        return CrossReferences()
    refs = CrossReferences()
    for m in _VZ_REQ_RE.finditer(text):
        rid = m.group()
        if rid not in refs.internal:
            refs.internal.append(rid)
    refs.standards = _extract_standards_refs(text)
    return refs
