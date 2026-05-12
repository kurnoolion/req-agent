"""Tests for the profile_patch → corrections-profile merger.

Covers the pure ``apply_patch`` core (no I/O) plus the file-level
``apply_patch_files`` orchestrator (seeding, multi-doc merge, dry-run).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.src.profile_miner.apply_patch import (
    apply_patch,
    apply_patch_files,
    merge_regex,
)


# ---------------------------------------------------------------------------
# merge_regex
# ---------------------------------------------------------------------------

def test_merge_regex_set_when_existing_empty():
    assert merge_regex("", "(?i)foo") == "(?i)foo"
    assert merge_regex("   ", "(?i)foo") == "(?i)foo"


def test_merge_regex_noop_when_identical():
    assert merge_regex("(?i)foo", "(?i)foo") == "(?i)foo"


def test_merge_regex_alternation_when_differs():
    out = merge_regex("(?i)foo", "(?i)bar")
    assert out == "(?i)(?:foo|bar)"


def test_merge_regex_dedupes_inline_flag():
    # Only one side has the flag — result keeps a single leading (?i).
    out = merge_regex("(?i)foo", "bar")
    assert out == "(?i)(?:foo|bar)"
    out2 = merge_regex("foo", "(?i)bar")
    assert out2 == "(?i)(?:foo|bar)"


def test_merge_regex_no_flag_when_neither_has_one():
    assert merge_regex("foo", "bar") == "(?:foo|bar)"


# ---------------------------------------------------------------------------
# apply_patch (pure function)
# ---------------------------------------------------------------------------

def _patch(entries: list[dict], unmapped: list[dict] | None = None) -> dict:
    return {
        "doc_id": "DOC1",
        "generated_at": "t",
        "field_patches": entries,
        "unmapped": unmapped or [],
    }


def test_apply_patch_sets_empty_field():
    patch = _patch([{
        "profile_field": "revhist_table_header_pattern",
        "list_field": False,
        "expected_reason": "revhist",
        "proposed_pattern": "(?i)rev\\.?\\s*\\|\\s*author",
        "rationale": "x", "confidence": 0.9,
    }])
    profile = {"revhist_table_header_pattern": ""}
    rep = apply_patch(patch, profile)
    assert profile["revhist_table_header_pattern"] == "(?i)rev\\.?\\s*\\|\\s*author"
    assert [c.action for c in rep.changes] == ["set"]


def test_apply_patch_merges_when_existing_differs():
    patch = _patch([{
        "profile_field": "revhist_table_header_pattern",
        "list_field": False,
        "expected_reason": "revhist",
        "proposed_pattern": "(?i)version\\s*\\|\\s*date",
        "rationale": "x", "confidence": 0.9,
    }])
    profile = {"revhist_table_header_pattern": "(?i)rev\\.\\s*\\|\\s*author"}
    rep = apply_patch(patch, profile)
    assert profile["revhist_table_header_pattern"].startswith("(?i)(?:")
    assert "rev\\.\\s*\\|\\s*author" in profile["revhist_table_header_pattern"]
    assert "version\\s*\\|\\s*date" in profile["revhist_table_header_pattern"]
    assert [c.action for c in rep.changes] == ["merged"]


def test_apply_patch_skips_when_already_present_string():
    patch = _patch([{
        "profile_field": "revhist_table_header_pattern",
        "list_field": False,
        "expected_reason": "revhist",
        "proposed_pattern": "(?i)rev",
        "rationale": "x", "confidence": 0.9,
    }])
    profile = {"revhist_table_header_pattern": "(?i)rev"}
    rep = apply_patch(patch, profile)
    assert profile["revhist_table_header_pattern"] == "(?i)rev"
    assert rep.changes[0].action == "skipped:already-present"


def test_apply_patch_dotted_path_for_heading_detection():
    patch = _patch([{
        "profile_field": "heading_detection.definitions_table_header_pattern",
        "list_field": False,
        "expected_reason": "glossary",
        "proposed_pattern": "(?i)acronym\\s*\\|\\s*definition",
        "rationale": "x", "confidence": 0.9,
    }])
    profile = {"heading_detection": {"method": "numbering"}}
    rep = apply_patch(patch, profile)
    assert profile["heading_detection"]["definitions_table_header_pattern"] == (
        "(?i)acronym\\s*\\|\\s*definition"
    )
    assert rep.changes[0].action == "set"


def test_apply_patch_appends_to_list_field():
    patch = _patch([{
        "profile_field": "cross_reference_patterns.standards_citations",
        "list_field": True,
        "expected_reason": "reference_spec",
        "proposed_pattern": r"GSMA\s+\w+[\d.]*",
        "rationale": "x", "confidence": 0.9,
    }])
    profile = {
        "cross_reference_patterns": {
            "standards_citations": [r"3GPP\s+TS\s+[\d.]+"],
        },
    }
    rep = apply_patch(patch, profile)
    assert profile["cross_reference_patterns"]["standards_citations"] == [
        r"3GPP\s+TS\s+[\d.]+", r"GSMA\s+\w+[\d.]*",
    ]
    assert rep.changes[0].action == "appended"


def test_apply_patch_skips_already_present_list_member():
    patch = _patch([{
        "profile_field": "cross_reference_patterns.standards_citations",
        "list_field": True,
        "expected_reason": "reference_spec",
        "proposed_pattern": r"3GPP\s+TS\s+[\d.]+",
        "rationale": "x", "confidence": 0.9,
    }])
    profile = {
        "cross_reference_patterns": {
            "standards_citations": [r"3GPP\s+TS\s+[\d.]+"],
        },
    }
    rep = apply_patch(patch, profile)
    assert rep.changes[0].action == "skipped:already-present"


def test_apply_patch_reports_unmapped_without_applying():
    patch = _patch(
        entries=[],
        unmapped=[{
            "profile_field": "<unmapped:reference_cross_doc>",
            "list_field": False,
            "expected_reason": "reference_cross_doc",
            "proposed_pattern": "(?i)plan\\s+\\w+",
            "rationale": "x", "confidence": 0.5,
        }],
    )
    profile = {}
    rep = apply_patch(patch, profile)
    assert rep.changes == []
    assert rep.skipped_unmapped == ["<unmapped:reference_cross_doc>"]
    assert profile == {}  # untouched


# ---------------------------------------------------------------------------
# apply_patch_files (file orchestrator)
# ---------------------------------------------------------------------------

def _write_patch(env_dir: Path, doc_id: str, field: str,
                 pattern: str, *, list_field: bool = False) -> None:
    (env_dir / "reports").mkdir(parents=True, exist_ok=True)
    payload = {
        "doc_id": doc_id, "generated_at": "t",
        "field_patches": [{
            "profile_field": field, "list_field": list_field,
            "expected_reason": "revhist", "proposed_pattern": pattern,
            "rationale": "x", "confidence": 0.9,
        }],
        "unmapped": [],
    }
    (env_dir / "reports" / f"profile_patch_{doc_id}.json").write_text(
        json.dumps(payload), encoding="utf-8",
    )


def _seed_output_profile(env_dir: Path, body: dict) -> None:
    out = env_dir / "out" / "profile"
    out.mkdir(parents=True, exist_ok=True)
    (out / "stub.json").write_text(json.dumps(body), encoding="utf-8")


def test_files_seeds_from_output_when_corrections_absent(tmp_path: Path):
    _seed_output_profile(tmp_path, {"profile_name": "x"})
    _write_patch(tmp_path, "DOC1", "revhist_table_header_pattern", "(?i)rev")
    rep, path = apply_patch_files(tmp_path)
    assert path == tmp_path / "corrections" / "profile.json"
    assert path.exists()
    loaded = json.loads(path.read_text())
    assert loaded["profile_name"] == "x"
    assert loaded["revhist_table_header_pattern"] == "(?i)rev"
    assert rep.modified


def test_files_merges_two_docs_into_one_field(tmp_path: Path):
    _seed_output_profile(tmp_path, {})
    _write_patch(tmp_path, "DOC1", "revhist_table_header_pattern", "(?i)rev\\s*\\|\\s*author")
    _write_patch(tmp_path, "DOC2", "revhist_table_header_pattern", "(?i)version\\s*\\|\\s*date")
    rep, path = apply_patch_files(tmp_path)
    loaded = json.loads(path.read_text())
    merged = loaded["revhist_table_header_pattern"]
    assert merged.startswith("(?i)(?:")
    assert "rev\\s*\\|\\s*author" in merged
    assert "version\\s*\\|\\s*date" in merged
    # First doc → set; second doc → merged.
    actions = [c.action for c in rep.changes]
    assert actions == ["set", "merged"]


def test_files_dry_run_does_not_write(tmp_path: Path):
    _seed_output_profile(tmp_path, {"revhist_table_header_pattern": ""})
    _write_patch(tmp_path, "DOC1", "revhist_table_header_pattern", "(?i)rev")
    rep, path = apply_patch_files(tmp_path, dry_run=True)
    assert rep.modified  # logically modified
    loaded = json.loads(path.read_text())
    # But the on-disk file is still the un-modified seeded copy.
    assert loaded["revhist_table_header_pattern"] == ""


def test_files_filters_by_doc(tmp_path: Path):
    _seed_output_profile(tmp_path, {})
    _write_patch(tmp_path, "DOC1", "revhist_table_header_pattern", "(?i)a")
    _write_patch(tmp_path, "DOC2", "revhist_table_header_pattern", "(?i)b")
    rep, path = apply_patch_files(tmp_path, doc_id="DOC2")
    loaded = json.loads(path.read_text())
    assert loaded["revhist_table_header_pattern"] == "(?i)b"
    # Only DOC2's patch applied — single 'set' change.
    assert [c.source_doc for c in rep.changes] == ["DOC2"]


def test_files_raises_when_no_seed_available(tmp_path: Path):
    _write_patch(tmp_path, "DOC1", "revhist_table_header_pattern", "(?i)rev")
    # No output/profile/*.json to seed from.
    with pytest.raises(FileNotFoundError):
        apply_patch_files(tmp_path)


def test_files_returns_empty_when_no_patches(tmp_path: Path):
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    rep, path = apply_patch_files(tmp_path)
    assert rep.changes == []
    assert path is None
