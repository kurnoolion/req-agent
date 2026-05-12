"""Cluster enriched corrections by ``expected_reason`` and ask an LLM
to propose one regex per cluster.

Public entrypoint: ``mine_patterns(corrections, llm) -> ProfilePatch``.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime

from core.src.llm.base import LLMProvider
from core.src.profile_miner.records import (
    EnrichedCorrection,
    ProfileFieldPatch,
    ProfilePatch,
)
from core.src.profile_miner.redaction import Redactor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# expected_reason → (profile field dotted path, is_list_field)
# ---------------------------------------------------------------------------

# (reason, is_table) → (profile field, is_list_field). A "table-shaped"
# correction (annotated on a TABLE block) routes revhist/glossary to the
# *_table_header_pattern field; everything else routes to the
# heading/paragraph-shaped field.
_REASON_TO_FIELD: dict[tuple[str, bool], tuple[str, bool]] = {
    ("revhist",              False): ("revision_history_label_pattern",                       False),
    ("revhist",              True):  ("revhist_table_header_pattern",                         False),
    ("dropped_revhist",      False): ("revision_history_label_pattern",                       False),
    ("dropped_revhist",      True):  ("revhist_table_header_pattern",                         False),
    ("glossary",             False): ("heading_detection.definitions_section_pattern",        False),
    ("glossary",             True):  ("heading_detection.definitions_table_header_pattern",   False),
    ("dropped_toc",          False): ("toc_detection_pattern",                                False),
    ("toc",                  False): ("toc_detection_pattern",                                False),
    ("reference_list",       False): ("reference_list_section_pattern",                       False),
    ("reference_list_entry", False): ("reference_list_entry_pattern",                         False),
    ("reference_intra_doc",  False): ("cross_reference_patterns.internal_section_refs",       False),
    ("reference_spec",       False): ("cross_reference_patterns.standards_citations",         True),
}


def _resolve_field(reason: str, is_table: bool) -> tuple[str, bool, bool]:
    """Return (profile_field, is_list_field, is_mapped)."""
    key = (reason, is_table)
    if key in _REASON_TO_FIELD:
        field, is_list = _REASON_TO_FIELD[key]
        return field, is_list, True
    # Try the other shape — some reasons (toc, reference_*) only make
    # sense for one block-type and we don't want to spuriously route
    # them to <unmapped:> just because the user mis-annotated a table.
    other = (reason, not is_table)
    if other in _REASON_TO_FIELD:
        field, is_list = _REASON_TO_FIELD[other]
        return field, is_list, True
    suffix = ":table" if is_table else ""
    return f"<unmapped:{reason}{suffix}>", False, False


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

_SYSTEM = """You are a regex-mining assistant for a document parser.

The parser is profile-driven: each Mobile Network Operator (MNO) ships
documents in a slightly different style, and the parser is configured
per-corpus with regex patterns that detect section headings, tables,
references, and other landmarks. When the parser misses a landmark, a
human marks the surrounding text block as a correction. Your job is to
look at one or more such corrections (all sharing the same correction
kind and block type) and propose ONE Python-flavoured regex that would
have caught them.

Rules:
- The patterns will be compiled with re.IGNORECASE.
- Anchor to the start of the line (``^``) only when every example is at
  the start of its block.
- Prefer broad-but-specific patterns; do not bake in proprietary text
  verbatim. Operator names and plan identifiers are pre-redacted to
  ``<MNO0>``, ``<PLAN0>``, etc — leave those placeholders intact if they
  appear in the example.
- The MATCHING TARGET line in each prompt tells you exactly what the
  parser will test the regex against. Generalise across the examples
  shown — if examples vary in case, word order, or punctuation, account
  for that in the regex.
- Return STRICT JSON with no surrounding prose:
  {
    "pattern":    "<your regex>",
    "rationale":  "<one short sentence>",
    "confidence": 0.0-1.0
  }
"""


def _matching_target_hint(reason: str, is_table: bool) -> str:
    """One-line hint about what string the proposed regex will be
    tested against at parse time. Lets the LLM produce something
    shaped right for the actual matching surface."""
    if is_table:
        return (
            "MATCHING TARGET: \" | \".join(table.headers)  "
            "— the joined column-header row of a TABLE block."
        )
    if reason in ("revhist", "dropped_revhist", "glossary",
                  "reference_list"):
        return (
            "MATCHING TARGET: the .strip()'d text of a HEADING / "
            "PARAGRAPH block (typically the section label)."
        )
    if reason in ("dropped_toc", "toc"):
        return "MATCHING TARGET: the .strip()'d text of a PARAGRAPH block."
    return "MATCHING TARGET: the .strip()'d text of the BLOCK shown."


def _example_target(c: EnrichedCorrection, is_table: bool) -> str:
    """Render the example in the shape the regex will be tested against
    (joined headers for tables; block text otherwise)."""
    if is_table and c.table_headers:
        return " | ".join(h.strip() for h in c.table_headers)
    return c.block_text


def _build_prompt(reason: str, is_table: bool,
                  cluster: list[EnrichedCorrection]) -> str:
    lines: list[str] = [
        f"Correction kind: {reason}",
        f"Block type: {'table' if is_table else 'heading/paragraph'}",
        _matching_target_hint(reason, is_table),
        f"Number of examples: {len(cluster)}",
        "",
        "Examples (one per correction):",
    ]
    for i, c in enumerate(cluster, 1):
        lines.append(f"--- example {i} (block_idx={c.block_idx}, pages={c.pages}) ---")
        lines.append(f"TARGET: {_example_target(c, is_table)}")
        if c.neighbour_texts:
            joined = " ⏎ ".join(c.neighbour_texts)
            lines.append(f"CONTEXT: {joined[:400]}")
        if c.comment:
            lines.append(f"USER COMMENT: {c.comment}")
    lines.append("")
    lines.append("Return only the JSON object described in the system prompt.")
    return "\n".join(lines)


_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)


def _strip_leading_iflag(pat: str) -> str:
    return pat[4:] if pat.startswith("(?i)") else pat


def _safety_net_pattern(
    llm_regex: str,
    cluster: list[EnrichedCorrection],
    is_table: bool,
) -> str:
    """Compose the final proposed pattern as
    ``(?i)(?:<llm_body>|<re.escape(ex1)>|<re.escape(ex2)>|...)`` so the
    regex is GUARANTEED to match its own examples even if the LLM
    overgeneralised (e.g. emitted ``Rev\\.`` when one of the examples
    was a plain ``Rev``).

    Compile-tests the LLM regex against every example. Examples that
    already match aren't escape-added (would just bloat the regex);
    examples that don't are appended as literal-escaped branches.
    Outer ``(?i)`` is applied once and any inline leading ``(?i)`` on
    branches is stripped to avoid Python 3.11+ mid-pattern flag warnings.
    """
    branches: list[str] = []
    seen: set[str] = set()

    # Verify the LLM regex compiles before including it as a branch.
    # An uncompilable branch would poison the whole alternation.
    try:
        rx = re.compile(llm_regex, re.IGNORECASE) if llm_regex else None
    except re.error as exc:
        logger.warning(
            "LLM regex doesn't compile (%s) — using literal-only fallback",
            exc,
        )
        rx = None

    llm_body = _strip_leading_iflag(llm_regex).strip()
    if llm_body and rx is not None:
        branches.append(llm_body)
        seen.add(llm_body)

    for c in cluster:
        target = _example_target(c, is_table)
        if not target:
            continue
        if rx is not None and rx.search(target):
            continue  # LLM regex already covers this example
        lit = re.escape(target)
        if lit in seen:
            continue
        branches.append(lit)
        seen.add(lit)

    if not branches:
        return ""
    if len(branches) == 1 and branches[0] == llm_body:
        # LLM regex covered all examples — no fallbacks needed.
        return f"(?i){llm_body}" if llm_body else ""
    return f"(?i)(?:{'|'.join(branches)})"


def _parse_llm_response(text: str) -> dict | None:
    """Tolerate code fences or stray prose. Returns None on parse
    failure; caller logs and synthesises a low-confidence fallback."""
    m = _JSON_OBJ.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

def mine_patterns(
    corrections: list[EnrichedCorrection],
    llm: LLMProvider,
) -> ProfilePatch:
    """Cluster corrections by ``expected_reason``, prompt the LLM once
    per cluster, and assemble the per-document ``ProfilePatch``.

    Caller is responsible for splitting corrections by ``doc_id`` if it
    wants one patch per doc (see ``profile_miner_cli``).
    """
    # Cluster by (reason, is_table). Table-shaped corrections produce
    # *_table_header_pattern proposals; everything else stays on the
    # paragraph/heading-shaped fields.
    by_cluster: dict[tuple[str, bool], list[EnrichedCorrection]] = defaultdict(list)
    for c in corrections:
        is_table = c.block_type == "table"
        by_cluster[(c.expected_reason, is_table)].append(c)

    doc_ids = sorted({c.doc_id for c in corrections})
    patch = ProfilePatch(
        doc_id=doc_ids[0] if len(doc_ids) == 1 else "multi",
        generated_at=datetime.now().isoformat(timespec="seconds"),
    )

    for (reason, is_table), cluster in by_cluster.items():
        if not reason:
            continue

        redactor = Redactor()
        # Redact each example's text + neighbours + table-headers in-place
        # before prompting. Fresh redactor per cluster so placeholder
        # indices are local to one prompt — less confusing for the LLM
        # than carrying global state across unrelated reasons.
        redacted: list[EnrichedCorrection] = []
        for c in cluster:
            redacted.append(EnrichedCorrection(
                doc_id=c.doc_id,
                kind=c.kind,
                expected_reason=c.expected_reason,
                block_idx=c.block_idx,
                pages=c.pages,
                block_text=redactor.redact(c.block_text),
                block_type=c.block_type,
                table_headers=[redactor.redact(h) for h in c.table_headers],
                neighbour_texts=[redactor.redact(t) for t in c.neighbour_texts],
                comment=redactor.redact(c.comment) if c.comment else "",
            ))

        prompt = _build_prompt(reason, is_table, redacted)
        try:
            raw = llm.complete(
                prompt=prompt,
                system=_SYSTEM,
                temperature=0.0,
                max_tokens=512,
            )
        except Exception as exc:
            logger.error(
                "LLM call failed for reason=%s is_table=%s: %s",
                reason, is_table, exc,
            )
            continue

        parsed = _parse_llm_response(raw)
        if parsed is None:
            logger.warning(
                "LLM returned unparseable JSON for reason=%s is_table=%s — raw=%r",
                reason, is_table, raw[:200],
            )
            continue

        field, is_list, mapped = _resolve_field(reason, is_table)
        llm_regex = str(parsed.get("pattern", "")).strip()
        # Belt-and-suspenders: if the LLM regex doesn't match every
        # example, OR in re.escape()'d literals for the uncovered ones.
        # Use the redacted examples — placeholders like <MNO0> survive
        # the escape and stay portable across MNOs/plans.
        final_pattern = _safety_net_pattern(llm_regex, redacted, is_table)
        fp = ProfileFieldPatch(
            profile_field=field,
            list_field=is_list,
            expected_reason=reason,
            proposed_pattern=final_pattern,
            rationale=str(parsed.get("rationale", "")).strip(),
            confidence=float(parsed.get("confidence", 0.0) or 0.0),
            example_block_idxs=[c.block_idx for c in cluster],
            example_previews=[
                _example_target(c, is_table)[:80] for c in cluster
            ],
        )
        if not fp.proposed_pattern:
            logger.warning(
                "LLM emitted empty pattern for reason=%s is_table=%s",
                reason, is_table,
            )
            continue

        (patch.field_patches if mapped else patch.unmapped).append(fp)

    return patch
