"""Tests for core/src/weaviate_store/standards_loader.py

No live Weaviate connection required — all tests cover pure-Python helpers:
  - _folder_to_doc_id
  - _rel_folder_to_release_id
  - _build_section_map
  - _lookup_text  (section / table / annex matching)
"""

from __future__ import annotations

import pytest

from core.src.weaviate_store.standards_loader import (
    _folder_to_doc_id,
    _rel_folder_to_release_id,
    _build_section_map,
    _lookup_text,
)


# ═══════════════════════════════════════════════════════════════════════════════
# _folder_to_doc_id
# ═══════════════════════════════════════════════════════════════════════════════

class TestFolderToDocId:
    def test_ts_prefix(self):
        assert _folder_to_doc_id("TS_23.503") == "23.503"

    def test_tr_prefix(self):
        assert _folder_to_doc_id("TR_38.913") == "38.913"

    def test_en_prefix(self):
        assert _folder_to_doc_id("EN_301.511") == "301.511"

    def test_es_prefix(self):
        assert _folder_to_doc_id("ES_202.050") == "202.050"

    def test_etsi_series(self):
        assert _folder_to_doc_id("TS_102.221") == "102.221"

    def test_no_prefix_passthrough(self):
        # Unknown prefix passed through unchanged
        assert _folder_to_doc_id("24.301") == "24.301"

    def test_hyphen_in_spec_number(self):
        assert _folder_to_doc_id("TS_38.101-1") == "38.101-1"


# ═══════════════════════════════════════════════════════════════════════════════
# _rel_folder_to_release_id
# ═══════════════════════════════════════════════════════════════════════════════

class TestRelFolderToReleaseId:
    def test_rel_15(self):
        assert _rel_folder_to_release_id("Rel-15") == "Release 15"

    def test_rel_9(self):
        assert _rel_folder_to_release_id("Rel-9") == "Release 9"

    def test_rel_17(self):
        assert _rel_folder_to_release_id("Rel-17") == "Release 17"

    def test_unknown_passthrough(self):
        assert _rel_folder_to_release_id("Release-15") == "Release-15"


# ═══════════════════════════════════════════════════════════════════════════════
# _build_section_map
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildSectionMap:
    def test_normal_sections(self):
        sections = [
            {"number": "4.1",   "text": "This clause defines..."},
            {"number": "4.2.1", "text": "The UE shall..."},
        ]
        m = _build_section_map(sections)
        assert m["4.1"]   == "This clause defines..."
        assert m["4.2.1"] == "The UE shall..."

    def test_empty_number_excluded(self):
        """Foreword and other un-numbered sections must be excluded."""
        sections = [
            {"number": "",    "text": "Foreword text"},
            {"number": "1",   "text": "Scope"},
        ]
        m = _build_section_map(sections)
        assert "" not in m
        assert "1" in m

    def test_blank_text_excluded(self):
        sections = [
            {"number": "4.1", "text": ""},
            {"number": "4.2", "text": "   "},
            {"number": "4.3", "text": "Real content"},
        ]
        m = _build_section_map(sections)
        assert "4.1" not in m
        assert "4.2" not in m
        assert "4.3" in m

    def test_none_values_handled(self):
        sections = [
            {"number": None, "text": "Some text"},
            {"number": "5",  "text": None},
            {"number": "6",  "text": "Valid"},
        ]
        m = _build_section_map(sections)
        assert "6" in m
        assert len(m) == 1

    def test_annex_sections_included(self):
        """Annex sections with letter-prefixed numbers must be included."""
        sections = [
            {"number": "A",       "text": "Annex A content"},
            {"number": "A.1",     "text": "Annex A.1 content"},
            {"number": "A.3.3.1", "text": "Annex A.3.3.1 content"},
            {"number": "B.2",     "text": "Annex B.2 content"},
        ]
        m = _build_section_map(sections)
        assert "A"       in m
        assert "A.1"     in m
        assert "A.3.3.1" in m
        assert "B.2"     in m

    def test_empty_sections_list(self):
        assert _build_section_map([]) == {}


# ═══════════════════════════════════════════════════════════════════════════════
# _lookup_text — section
# ═══════════════════════════════════════════════════════════════════════════════

class TestLookupTextSection:
    def _map(self):
        return {
            "4.1":   "Section 4.1 text",
            "4.2.1": "Section 4.2.1 text",
            "A.3":   "Annex A.3 text",
        }

    def test_section_direct_match(self):
        assert _lookup_text("section", "4.1", self._map()) == "Section 4.1 text"

    def test_section_nested(self):
        assert _lookup_text("section", "4.2.1", self._map()) == "Section 4.2.1 text"

    def test_section_not_found_returns_none(self):
        assert _lookup_text("section", "9.9.9", self._map()) is None

    def test_section_empty_content_id(self):
        assert _lookup_text("section", "", self._map()) is None


# ═══════════════════════════════════════════════════════════════════════════════
# _lookup_text — table (strip -N suffix)
# ═══════════════════════════════════════════════════════════════════════════════

class TestLookupTextTable:
    def _map(self):
        return {
            "4.1":    "Section 4.1 text",
            "5.2D":   "Section 5.2D text",
            "5.3A.2": "Section 5.3A.2 text",
            "5.3.3":  "Section 5.3.3 text",
            "6.2A.2.4": "Section 6.2A.2.4 text",
        }

    def test_simple_table_ref(self):
        """4.1-1 → base 4.1"""
        assert _lookup_text("table", "4.1-1", self._map()) == "Section 4.1 text"

    def test_letter_suffix_section(self):
        """5.2D-1 → base 5.2D"""
        assert _lookup_text("table", "5.2D-1", self._map()) == "Section 5.2D text"

    def test_mixed_letter_in_section(self):
        """5.3A.2-2 → base 5.3A.2"""
        assert _lookup_text("table", "5.3A.2-2", self._map()) == "Section 5.3A.2 text"

    def test_nested_numeric_section(self):
        """5.3.3-2 → base 5.3.3"""
        assert _lookup_text("table", "5.3.3-2", self._map()) == "Section 5.3.3 text"

    def test_deep_nested_with_letter(self):
        """6.2A.2.4-1 → base 6.2A.2.4"""
        assert _lookup_text("table", "6.2A.2.4-1", self._map()) == "Section 6.2A.2.4 text"

    def test_multi_digit_table_number(self):
        """5.3.3-12 → base 5.3.3"""
        assert _lookup_text("table", "5.3.3-12", self._map()) == "Section 5.3.3 text"

    def test_table_parent_section_not_in_map(self):
        assert _lookup_text("table", "9.9-1", self._map()) is None

    def test_table_no_hyphen_fallback(self):
        """Table content_id with no hyphen — try direct match."""
        m = {"4.1": "Section 4.1 text"}
        assert _lookup_text("table", "4.1", m) == "Section 4.1 text"


# ═══════════════════════════════════════════════════════════════════════════════
# _lookup_text — annex
# ═══════════════════════════════════════════════════════════════════════════════

class TestLookupTextAnnex:
    def _map(self):
        return {
            "A":         "Annex A top-level",
            "A.1":       "Annex A.1 text",
            "A.3.3.1.2": "Annex A.3.3.1.2 text",
            "B.2":       "Annex B.2 text",
        }

    def test_top_level_annex(self):
        assert _lookup_text("annex", "A", self._map()) == "Annex A top-level"

    def test_annex_subsection(self):
        assert _lookup_text("annex", "A.1", self._map()) == "Annex A.1 text"

    def test_deep_annex_subsection(self):
        assert _lookup_text("annex", "A.3.3.1.2", self._map()) == "Annex A.3.3.1.2 text"

    def test_annex_b(self):
        assert _lookup_text("annex", "B.2", self._map()) == "Annex B.2 text"

    def test_annex_not_found(self):
        assert _lookup_text("annex", "C.1", self._map()) is None


# ═══════════════════════════════════════════════════════════════════════════════
# _lookup_text — unknown content_type
# ═══════════════════════════════════════════════════════════════════════════════

class TestLookupTextUnknown:
    def test_unknown_type_direct_match(self):
        m = {"4.1": "text"}
        assert _lookup_text("figure", "4.1", m) == "text"

    def test_unknown_type_not_found(self):
        m = {"4.1": "text"}
        assert _lookup_text("figure", "9.9", m) is None
