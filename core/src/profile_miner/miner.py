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

_REASON_TO_FIELD: dict[str, tuple[str, bool]] = {
    "revhist":              ("revision_history_label_pattern",                  False),
    "dropped_revhist":      ("revision_history_label_pattern",                  False),
    "glossary":             ("heading_detection.definitions_section_pattern",   False),
    "dropped_toc":          ("toc_detection_pattern",                           False),
    "toc":                  ("toc_detection_pattern",                           False),
    "reference_list":       ("reference_list_section_pattern",                  False),
    "reference_list_entry": ("reference_list_entry_pattern",                    False),
    "reference_intra_doc":  ("cross_reference_patterns.internal_section_refs",  False),
    "reference_spec":       ("cross_reference_patterns.standards_citations",    True),
}
"""``reference_cross_doc`` is intentionally absent — see ``_resolve_field``."""


def _resolve_field(reason: str) -> tuple[str, bool, bool]:
    """Return (profile_field, is_list_field, is_mapped). For unmapped
    reasons the patch is emitted to the ``unmapped`` list so the reviewer
    can place it manually."""
    if reason in _REASON_TO_FIELD:
        field, is_list = _REASON_TO_FIELD[reason]
        return field, is_list, True
    return f"<unmapped:{reason}>", False, False


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

_SYSTEM = """You are a regex-mining assistant for a document parser.

The parser is profile-driven: each Mobile Network Operator (MNO) ships
documents in a slightly different style, and the parser is configured
per-corpus with regex patterns that detect section headings, references,
and other landmarks. When the parser misses a landmark, a human marks
the surrounding text block as a correction. Your job is to look at one
or more such corrections (all sharing the same correction kind) and
propose ONE Python-flavoured regex that would have caught them.

Rules:
- The patterns will be compiled with re.IGNORECASE.
- Anchor to the start of the line (``^``) only when every example is at
  the start of its block.
- Prefer broad-but-specific patterns; do not bake in proprietary text
  verbatim. Operator names and plan identifiers are pre-redacted to
  ``<MNO0>``, ``<PLAN0>``, etc — leave those placeholders intact if they
  appear in the example.
- Return STRICT JSON with no surrounding prose:
  {
    "pattern":    "<your regex>",
    "rationale":  "<one short sentence>",
    "confidence": 0.0-1.0
  }
"""


def _build_prompt(reason: str, cluster: list[EnrichedCorrection]) -> str:
    lines: list[str] = [
        f"Correction kind: {reason}",
        f"Number of examples: {len(cluster)}",
        "",
        "Examples (one per correction):",
    ]
    for i, c in enumerate(cluster, 1):
        lines.append(f"--- example {i} (block_idx={c.block_idx}, pages={c.pages}) ---")
        lines.append(f"BLOCK: {c.block_text}")
        if c.neighbour_texts:
            joined = " ⏎ ".join(c.neighbour_texts)
            lines.append(f"CONTEXT: {joined[:400]}")
        if c.comment:
            lines.append(f"USER COMMENT: {c.comment}")
    lines.append("")
    lines.append("Return only the JSON object described in the system prompt.")
    return "\n".join(lines)


_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)


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
    by_reason: dict[str, list[EnrichedCorrection]] = defaultdict(list)
    for c in corrections:
        by_reason[c.expected_reason].append(c)

    doc_ids = sorted({c.doc_id for c in corrections})
    patch = ProfilePatch(
        doc_id=doc_ids[0] if len(doc_ids) == 1 else "multi",
        generated_at=datetime.now().isoformat(timespec="seconds"),
    )

    for reason, cluster in by_reason.items():
        if not reason:
            continue

        redactor = Redactor()
        # Redact each example's text + neighbours in-place before
        # prompting. We allocate a fresh redactor per cluster so token
        # indices are local to the cluster (less confusing for the LLM
        # than carrying global state across unrelated reasons).
        redacted: list[EnrichedCorrection] = []
        for c in cluster:
            redacted.append(EnrichedCorrection(
                doc_id=c.doc_id,
                kind=c.kind,
                expected_reason=c.expected_reason,
                block_idx=c.block_idx,
                pages=c.pages,
                block_text=redactor.redact(c.block_text),
                neighbour_texts=[redactor.redact(t) for t in c.neighbour_texts],
                comment=redactor.redact(c.comment) if c.comment else "",
            ))

        prompt = _build_prompt(reason, redacted)
        try:
            raw = llm.complete(
                prompt=prompt,
                system=_SYSTEM,
                temperature=0.0,
                max_tokens=512,
            )
        except Exception as exc:
            logger.error("LLM call failed for reason=%s: %s", reason, exc)
            continue

        parsed = _parse_llm_response(raw)
        if parsed is None:
            logger.warning(
                "LLM returned unparseable JSON for reason=%s — raw=%r",
                reason, raw[:200],
            )
            continue

        field, is_list, mapped = _resolve_field(reason)
        fp = ProfileFieldPatch(
            profile_field=field,
            list_field=is_list,
            expected_reason=reason,
            proposed_pattern=str(parsed.get("pattern", "")).strip(),
            rationale=str(parsed.get("rationale", "")).strip(),
            confidence=float(parsed.get("confidence", 0.0) or 0.0),
            example_block_idxs=[c.block_idx for c in cluster],
            example_previews=[c.block_text[:80] for c in cluster],
        )
        if not fp.proposed_pattern:
            logger.warning("LLM emitted empty pattern for reason=%s", reason)
            continue

        (patch.field_patches if mapped else patch.unmapped).append(fp)

    return patch
