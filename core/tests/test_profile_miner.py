"""Tests for the profile_miner module.

Covers:
- Redactor round-trip: idempotent placeholder assignment, req-id
  composition, plan-id sweep guarded by ``Plan Id:`` / ``Plan Name:``.
- load_corrections: joins corrections to IR via block_idx, skips
  entries with stale/missing block_idx, includes neighbour text.
- mine_patterns: clusters by expected_reason, calls the LLM once per
  cluster, maps reasons to the right profile field, routes unmapped
  reasons separately.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.src.models.document import (
    BlockType,
    ContentBlock,
    DocumentIR,
    FontInfo,
    Position,
)
from core.src.profile_miner.loader import load_corrections
from core.src.profile_miner.miner import mine_patterns
from core.src.profile_miner.records import EnrichedCorrection
from core.src.profile_miner.redaction import Redactor


# ---------------------------------------------------------------------------
# Redactor
# ---------------------------------------------------------------------------

def test_redactor_mno_indexing_is_stable():
    r = Redactor()
    out = r.redact("Verizon and AT&T and Verizon again")
    # Same surface → same placeholder; different surface → next index.
    assert out.count("<MNO0>") == 2
    assert "<MNO1>" in out


def test_redactor_composes_req_id_token():
    r = Redactor()
    out = r.redact("See VZ_REQ_LTEDATARETRY_2365 in §1.2")
    # Numeric tail becomes \d+; MNO and PLAN are tokenised.
    assert out == "See <MNO0>_REQ_<PLAN0>_\\d+ in §1.2"


def test_redactor_plan_id_only_after_marker():
    r = Redactor()
    # Plain UPPERCASE words mid-sentence are NOT plan IDs and must
    # survive redaction.
    out = r.redact("The TABLE column contains ACRONYMS.")
    assert "TABLE" in out and "ACRONYMS" in out

    out2 = r.redact("Plan Id: LTEDATARETRY")
    assert "<PLAN0>" in out2


def test_redactor_is_idempotent():
    r = Redactor()
    once = r.redact("Verizon LTEDATARETRY Plan Id: LTEDATARETRY")
    twice = r.redact(once)
    assert once == twice


# ---------------------------------------------------------------------------
# load_corrections
# ---------------------------------------------------------------------------

def _make_block(idx: int, page: int, text: str) -> ContentBlock:
    return ContentBlock(
        type=BlockType.PARAGRAPH,
        position=Position(page=page, index=idx),
        text=text,
        runs=[],
        font_info=FontInfo(size=12.0),
    )


def _write_ir(env_dir: Path, doc_id: str, blocks: list[ContentBlock]) -> None:
    ir = DocumentIR(
        source_file=f"{doc_id}.docx",
        source_format="docx",
        mno="vzw",
        release="2026Q1",
        content_blocks=blocks,
    )
    ir_dir = env_dir / "out" / "extract"
    ir_dir.mkdir(parents=True, exist_ok=True)
    ir.save_json(ir_dir / f"{doc_id}_ir.json")


def _write_corrections(env_dir: Path, doc_id: str, missed: list[dict],
                       fp: list[dict] | None = None) -> None:
    corr_dir = env_dir / "corrections"
    corr_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "doc_id": doc_id,
        "reviewer": "t",
        "review_date": "2026-05-12",
        "corrections": {
            "missed_drops": missed,
            "false_positive_drops": fp or [],
        },
    }
    (corr_dir / f"{doc_id}_corrections.json").write_text(
        json.dumps(payload), encoding="utf-8",
    )


def test_loader_joins_block_idx_and_neighbours(tmp_path: Path):
    blocks = [_make_block(i, 1, f"line {i}") for i in range(5)]
    _write_ir(tmp_path, "DOC1", blocks)
    _write_corrections(tmp_path, "DOC1", missed=[{
        "pages": "1",
        "block_idx": 2,
        "expected_reason": "revhist",
        "comment": "this is the revhist heading",
    }])

    out = load_corrections(tmp_path)
    assert len(out) == 1
    e = out[0]
    assert e.doc_id == "DOC1"
    assert e.block_idx == 2
    assert e.block_text == "line 2"
    # ±2 neighbours, excluding the corrected block itself.
    assert e.neighbour_texts == ["line 0", "line 1", "line 3", "line 4"]
    assert e.expected_reason == "revhist"
    assert e.comment == "this is the revhist heading"


def test_loader_skips_stale_block_idx(tmp_path: Path, caplog):
    blocks = [_make_block(i, 1, f"x{i}") for i in range(3)]
    _write_ir(tmp_path, "DOC1", blocks)
    _write_corrections(tmp_path, "DOC1", missed=[{
        "pages": "1",
        "block_idx": 999,
        "expected_reason": "glossary",
    }])
    out = load_corrections(tmp_path)
    assert out == []


def test_loader_filters_by_doc(tmp_path: Path):
    for doc_id in ("DOC1", "DOC2"):
        _write_ir(tmp_path, doc_id, [_make_block(0, 1, doc_id)])
        _write_corrections(tmp_path, doc_id, missed=[{
            "pages": "1", "block_idx": 0, "expected_reason": "revhist",
        }])

    out = load_corrections(tmp_path, doc_id="DOC2")
    assert [e.doc_id for e in out] == ["DOC2"]


# ---------------------------------------------------------------------------
# mine_patterns
# ---------------------------------------------------------------------------

class _ScriptedLLM:
    """LLMProvider stub that returns the next scripted response on each
    call. Lets the test assert prompt content via captured calls."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, prompt: str, system: str = "",
                 temperature: float = 0.0, max_tokens: int = 4096) -> str:
        self.calls.append({"prompt": prompt, "system": system})
        return self._responses.pop(0)


def _ec(doc: str, reason: str, idx: int, text: str) -> EnrichedCorrection:
    return EnrichedCorrection(
        doc_id=doc, kind="missed", expected_reason=reason,
        block_idx=idx, pages="1", block_text=text,
    )


def test_miner_clusters_by_reason_and_maps_field():
    corrections = [
        _ec("DOC1", "revhist", 5, "Document History"),
        _ec("DOC1", "revhist", 12, "Change History"),
        _ec("DOC1", "glossary", 30, "Acronyms"),
    ]
    llm = _ScriptedLLM([
        # revhist cluster
        '{"pattern": "(?i)^(document|change|revision)\\\\s+history$",'
        ' "rationale": "matches all three variants", "confidence": 0.9}',
        # glossary cluster
        '{"pattern": "(?i)^acronyms$",'
        ' "rationale": "matches the heading", "confidence": 0.8}',
    ])
    patch = mine_patterns(corrections, llm)
    assert len(patch.field_patches) == 2
    by_field = {p.profile_field: p for p in patch.field_patches}
    assert "revision_history_label_pattern" in by_field
    assert "heading_detection.definitions_section_pattern" in by_field
    rev = by_field["revision_history_label_pattern"]
    assert rev.example_block_idxs == [5, 12]
    assert rev.confidence == 0.9


def test_miner_routes_unmapped_reasons_separately():
    corrections = [_ec("DOC1", "reference_cross_doc", 7, "See Plan FOO")]
    llm = _ScriptedLLM([
        '{"pattern": "(?i)see\\\\s+plan\\\\s+\\\\w+",'
        ' "rationale": "x", "confidence": 0.5}',
    ])
    patch = mine_patterns(corrections, llm)
    assert patch.field_patches == []
    assert len(patch.unmapped) == 1
    assert patch.unmapped[0].profile_field.startswith("<unmapped:")


def test_miner_tolerates_garbage_llm_output(caplog):
    corrections = [_ec("DOC1", "revhist", 1, "Revision History")]
    llm = _ScriptedLLM(["this is not json"])
    patch = mine_patterns(corrections, llm)
    assert patch.field_patches == []
    assert patch.unmapped == []


def test_miner_routes_table_revhist_to_table_header_field():
    corrections = [EnrichedCorrection(
        doc_id="DOC1", kind="missed", expected_reason="revhist",
        block_idx=5, pages="1", block_text="Rev. | Author | Date",
        block_type="table",
        table_headers=["Rev.", "Author", "Description of Changes", "Date"],
    )]
    llm = _ScriptedLLM([
        '{"pattern": "(?i)rev\\\\..*author.*date",'
        ' "rationale": "matches the revhist column header signature",'
        ' "confidence": 0.85}',
    ])
    patch = mine_patterns(corrections, llm)
    assert len(patch.field_patches) == 1
    fp = patch.field_patches[0]
    assert fp.profile_field == "revhist_table_header_pattern"
    # Example previews should be the joined headers (matching target),
    # not the BLOCK text — that's what the regex will be tested against.
    assert fp.example_previews[0].startswith("Rev. | Author")


def test_miner_routes_table_glossary_to_table_header_field():
    corrections = [EnrichedCorrection(
        doc_id="DOC1", kind="missed", expected_reason="glossary",
        block_idx=12, pages="2", block_text="Acronym | Definition",
        block_type="table",
        table_headers=["Acronym", "Definition"],
    )]
    llm = _ScriptedLLM([
        '{"pattern": "(?i)acronym\\\\s*\\\\|\\\\s*definition",'
        ' "rationale": "x", "confidence": 0.9}',
    ])
    patch = mine_patterns(corrections, llm)
    assert len(patch.field_patches) == 1
    assert patch.field_patches[0].profile_field == (
        "heading_detection.definitions_table_header_pattern"
    )


def test_miner_prompt_carries_matching_target_hint():
    corrections = [EnrichedCorrection(
        doc_id="DOC1", kind="missed", expected_reason="revhist",
        block_idx=5, pages="1", block_text="not used",
        block_type="table",
        table_headers=["Rev.", "Author", "Description of Changes", "Date"],
    )]
    llm = _ScriptedLLM([
        '{"pattern": "x", "rationale": "y", "confidence": 0.5}',
    ])
    mine_patterns(corrections, llm)
    sent = llm.calls[0]["prompt"]
    # The prompt must tell the LLM what it'll match against and show
    # the joined-header form of each example.
    assert "MATCHING TARGET:" in sent
    assert "table.headers" in sent
    assert "Rev. | Author | Description of Changes | Date" in sent


def test_miner_redacts_before_prompting():
    corrections = [_ec(
        "DOC1", "revhist", 1,
        "VZ_REQ_LTEDATARETRY_2365 — Verizon revision history",
    )]
    llm = _ScriptedLLM([
        '{"pattern": "x", "rationale": "y", "confidence": 0.5}',
    ])
    mine_patterns(corrections, llm)
    sent = llm.calls[0]["prompt"]
    # Raw req-id and operator name must not reach the LLM.
    assert "VZ_REQ_LTEDATARETRY_2365" not in sent
    assert "Verizon" not in sent
    assert "<MNO0>" in sent
    assert "<PLAN0>" in sent
