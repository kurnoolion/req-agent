"""Citation audit (Stage 6.5).

Post-synthesis pass over the LLM's answer that flags every sentence
without an inline citation and every citation that doesn't trace
back to a chunk in the LLM's context.

Two error classes the audit catches:

  1. Uncited factual claims — the LLM made a statement and didn't
     attach a (VZ_REQ_X) or (3GPP TS Y) citation. May be paraphrasing
     correctly, may be hallucinating; the audit flags but doesn't
     classify.

  2. Fabricated citations — the LLM cited a req ID that doesn't
     appear in the available_req_ids set (the chunks it actually
     received). Worst-case: looks authoritative, isn't real.

The audit is computed cheaply (no LLM call) and surfaces in
QueryResponse.citation_audit. The web Test page renders the
summary; a future "citation repair" pass (Phase 5c) could re-prompt
the LLM to add citations to flagged sentences.
"""

from __future__ import annotations

import re

from core.src.query.schema import CitationAudit, SentenceAudit


# ── Citation patterns (mirror synthesizer._extract_citations) ───

_REQ_ID_RE = re.compile(r"\b(VZ_REQ_\w+?_\d+)\b")
_SPEC_RE = re.compile(
    r"3GPP\s+TS\s+\d[\d.]*\d(?:[, ]\s*[Ss]ec\w*\s+\d[\d.]*\d)?",
)


# ── Sentence detection ──────────────────────────────────────────

# Common abbreviations that end with a period but don't terminate a
# sentence. The list is conservative — false positives (treating a
# real sentence end as an abbreviation) lead to under-counted
# sentences; false negatives (treating an abbreviation as a sentence
# end) over-count. Add patterns when corpus shows actual misses.
_ABBREVIATIONS = (
    "e.g.", "i.e.", "etc.", "vs.", "v.", "approx.", "approxi.",
    "Mr.", "Ms.", "Dr.", "Inc.", "Ltd.", "Co.", "Corp.",
    "Sec.", "sec.",
    "Fig.", "fig.",
    "No.", "no.",
)


def _split_sentences(text: str) -> list[str]:
    """Split answer text into sentence-shaped fragments.

    Approach:
      1. Normalize line breaks; split into lines.
      2. Each non-empty line is at most one paragraph; further split
         by sentence-ending punctuation followed by space + uppercase
         (or end of line).
      3. Bullet/numbered list items count as their own sentences.
      4. Markdown header lines (starting with `#`, `**`, etc.) are
         preserved as their own sentences so the audit can mark them
         meta.

    Returns: list of trimmed sentence strings, in document order.
    Empty strings are dropped.
    """
    if not text:
        return []

    out: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Bullet / numbered list prefix? Treat each item as one
        # sentence regardless of internal punctuation. Strip the
        # bullet for detection purposes but keep the original text
        # in the output (the user reads the bullet).
        body_for_split = _strip_bullet_prefix(line)

        # Markdown header? Whole line is one sentence (will be
        # marked meta downstream).
        if _is_markdown_header(line):
            out.append(line)
            continue

        # Split on sentence-ending punctuation followed by whitespace
        # + uppercase or end-of-line. Keep the punctuation with the
        # preceding chunk.
        for sentence in _split_on_punct(body_for_split):
            sentence = sentence.strip()
            if sentence:
                out.append(sentence)

    return out


def _strip_bullet_prefix(line: str) -> str:
    """Return the line minus a leading bullet/numbered marker, if any."""
    # Bullets: -, *, • (with following space)
    m = re.match(r"^\s*[-*•]\s+(.*)", line)
    if m:
        return m.group(1)
    # Numbered: "1.", "2)", "1.1.", etc.
    m = re.match(r"^\s*\d+(?:\.\d+)*[.)]\s+(.*)", line)
    if m:
        return m.group(1)
    return line


def _is_markdown_header(line: str) -> bool:
    """Treat markdown headers (#, ##, **bold-only line**) as meta."""
    stripped = line.strip()
    if stripped.startswith("#"):
        return True
    # Pure bold line (e.g. "**TL;DR**" or "**Per-section breakdown**")
    if stripped.startswith("**") and stripped.endswith("**"):
        # No content outside the bold markers? Treat as header.
        inner = stripped[2:-2].strip()
        if inner and ":" not in inner[-3:]:
            # "**TL;DR**" → header; "**Note**: foo" → not (has body)
            return True
        if inner and inner.endswith(":"):
            return True
    return False


def _split_on_punct(text: str) -> list[str]:
    """Sentence-end punct splitter that respects abbreviations."""
    # Mark abbreviation periods with a placeholder so the regex below
    # doesn't split on them. Restore after.
    SENT = "\x00"  # placeholder for "abbreviation period"
    masked = text
    for abbr in _ABBREVIATIONS:
        masked = masked.replace(abbr, abbr.replace(".", SENT))

    # Split on `[.?!]+` followed by whitespace + uppercase letter or
    # end-of-string. Capture the punctuation so we can re-attach it.
    # Use re.split so we can post-process.
    parts = re.split(r"(?<=[.?!])\s+(?=[A-Z(])", masked)
    return [p.replace(SENT, ".") for p in parts]


# ── The audit ───────────────────────────────────────────────────


def audit_answer_citations(
    answer: str,
    available_req_ids: list[str] | None = None,
) -> CitationAudit:
    """Walk an answer sentence-by-sentence; tag citations and meta.

    Args:
        answer: The LLM's synthesized answer text.
        available_req_ids: Req IDs that were in the LLM's context.
            Citations in the answer not in this list are flagged
            as fabricated. Pass None or empty to skip the
            fabrication check (every citation will pass).

    Returns:
        CitationAudit with per-sentence breakdown + summary counts.
    """
    available = set(available_req_ids or [])
    sentences = _split_sentences(answer)

    audited: list[SentenceAudit] = []
    cited_count = 0
    factual_count = 0
    fabricated_count = 0

    for s in sentences:
        # Find req_id and 3GPP spec citations.
        req_ids = list(set(_REQ_ID_RE.findall(s)))
        specs = list(set(_SPEC_RE.findall(s)))
        all_citations = req_ids + specs

        # Detect fabricated req_ids.
        fabricated = []
        if available:
            fabricated = [r for r in req_ids if r not in available]

        is_meta = _is_markdown_header(s) or _is_label_only(s)
        has_citation = bool(all_citations)

        sa = SentenceAudit(
            text=s,
            has_citation=has_citation,
            citations_found=all_citations,
            fabricated_citations=fabricated,
            is_meta=is_meta,
        )
        audited.append(sa)
        if not is_meta:
            factual_count += 1
            if has_citation:
                cited_count += 1
        fabricated_count += len(fabricated)

    return CitationAudit(
        sentences=audited,
        cited_sentence_count=cited_count,
        factual_sentence_count=factual_count,
        fabricated_count=fabricated_count,
        available_req_ids=list(available_req_ids or []),
    )


def _is_label_only(s: str) -> bool:
    """Detect lines that are just a label like 'Direct answer:' —
    they're scaffolding, not factual claims."""
    if len(s) > 80:
        return False
    # Ends with a colon and has no inline period after the colon →
    # likely a section label.
    return s.rstrip().endswith(":") and "." not in s.split(":")[0]
