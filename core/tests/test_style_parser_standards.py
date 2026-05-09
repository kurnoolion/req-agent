"""Tests for _extract_standards_refs in style_parser.py.

Covers all compound patterns and the fallback, using examples from the
VZW requirement spec images reviewed during implementation.
"""

from __future__ import annotations

import pytest

from core.src.parser.style_parser import _extract_standards_refs
from core.src.parser.structural_parser import StandardsRef


# ── helpers ──────────────────────────────────────────────────────────────────


def _specs(refs: list[StandardsRef]) -> list[str]:
    return [r.spec for r in refs]


def _find(refs: list[StandardsRef], spec_fragment: str) -> StandardsRef | None:
    for r in refs:
        if spec_fragment in r.spec:
            return r
    return None


# ── Pattern 1: Table X in SPEC ───────────────────────────────────────────────


class TestTableInSpec:
    def test_basic_table_reference(self):
        text = "as defined in Table 7.4-1 in 3GPP TS 38.521-1"
        refs = _extract_standards_refs(text)
        r = _find(refs, "38.521-1")
        assert r is not None
        assert r.table == "7.4-1"
        assert r.section == ""
        assert r.annex == ""

    def test_lowercase_table(self):
        text = "see table 5.1 in TS 36.331"
        refs = _extract_standards_refs(text)
        r = _find(refs, "36.331")
        assert r is not None
        assert r.table == "5.1"

    def test_table_not_double_emitted(self):
        text = "Table 5.1 in 3GPP TS 36.331"
        refs = _extract_standards_refs(text)
        specs = _specs(refs)
        assert specs.count("3GPP TS 36.331") == 1


# ── Pattern 2: Annex X of SPEC ───────────────────────────────────────────────


class TestAnnexOfSpec:
    def test_basic_annex(self):
        text = "refer to Annex A of 3GPP TS 24.301"
        refs = _extract_standards_refs(text)
        r = _find(refs, "24.301")
        assert r is not None
        assert r.annex == "A"
        assert r.table == ""

    def test_annex_with_sub_id(self):
        text = "Annex L.1 of TS 36.331"
        refs = _extract_standards_refs(text)
        r = _find(refs, "36.331")
        assert r is not None
        assert r.annex == "L.1"

    def test_lowercase_annex(self):
        text = "annex B of 3GPP TS 38.101-1"
        refs = _extract_standards_refs(text)
        r = _find(refs, "38.101-1")
        assert r is not None
        assert r.annex == "B"


# ── Pattern 3: Section X of vN.M.P [...] of SPEC ─────────────────────────────


class TestSectionVersionOf:
    def test_version_encodes_release(self):
        text = "Section 5.3.1 of v15.6.0 of 3GPP TS 24.301"
        refs = _extract_standards_refs(text)
        r = _find(refs, "24.301")
        assert r is not None
        assert r.section == "5.3.1"
        assert r.release == "Release 15"

    def test_version_16(self):
        text = "section 4.2 of v16.0.1 of TS 38.521-1"
        refs = _extract_standards_refs(text)
        r = _find(refs, "38.521-1")
        assert r is not None
        assert r.release == "Release 16"


# ── Pattern 4: Section(s) X,Y,Z of SPEC ─────────────────────────────────────


class TestSectionsOf:
    def test_single_section(self):
        text = "Section 5.5.1 of 3GPP TS 24.301"
        refs = _extract_standards_refs(text)
        r = _find(refs, "24.301")
        assert r is not None
        assert r.section == "5.5.1"

    def test_multiple_sections_produce_separate_refs(self):
        text = "Sections 5.3.1 and 5.3.2 of 3GPP TS 24.301"
        refs = _extract_standards_refs(text)
        sec_refs = [r for r in refs if "24.301" in r.spec]
        sections = {r.section for r in sec_refs}
        assert "5.3.1" in sections
        assert "5.3.2" in sections

    def test_slash_separated_sections(self):
        text = "Sections 4.2.7.10/4.2.7.2 of TS 36.331"
        refs = _extract_standards_refs(text)
        sec_refs = [r for r in refs if "36.331" in r.spec]
        sections = {r.section for r in sec_refs}
        assert "4.2.7.10" in sections
        assert "4.2.7.2" in sections

    def test_release_from_context(self):
        text = "Release 10, Section 5.5.1 of 3GPP TS 24.301"
        refs = _extract_standards_refs(text)
        r = _find(refs, "24.301")
        assert r is not None
        assert r.release == "Release 10"


# ── Pattern 5: 3GPP Release N version of SPEC ───────────────────────────────


class TestReleaseVersionOf:
    def test_basic_release_version(self):
        text = "3GPP Release 10 version of 3GPP TS 24.301"
        refs = _extract_standards_refs(text)
        r = _find(refs, "24.301")
        assert r is not None
        assert r.release == "Release 10"

    def test_release_version_ts(self):
        text = "3GPP Release 15 version of TS 38.101-1"
        refs = _extract_standards_refs(text)
        r = _find(refs, "38.101-1")
        assert r is not None
        assert r.release == "Release 15"


# ── Pattern 6: SPEC Annex X ──────────────────────────────────────────────────


class TestSpecAnnex:
    def test_spec_then_annex(self):
        text = "3GPP TS 24.301 Annex C"
        refs = _extract_standards_refs(text)
        r = _find(refs, "24.301")
        assert r is not None
        assert r.annex == "C"

    def test_spec_specification_annex(self):
        text = "TS 36.331 specification Annex A"
        refs = _extract_standards_refs(text)
        r = _find(refs, "36.331")
        assert r is not None
        assert r.annex == "A"

    def test_not_double_emitted(self):
        text = "3GPP TS 24.301 Annex C"
        refs = _extract_standards_refs(text)
        specs = _specs(refs)
        assert specs.count("3GPP TS 24.301") == 1


# ── Pattern 7: SPEC section(s) X,Y ──────────────────────────────────────────


class TestSpecSections:
    def test_spec_section(self):
        text = "3GPP TS 24.301 section 5.5.1"
        refs = _extract_standards_refs(text)
        r = _find(refs, "24.301")
        assert r is not None
        assert r.section == "5.5.1"

    def test_spec_sections_plural(self):
        text = "TS 36.331 sections 6.3.1 and 6.3.2"
        refs = _extract_standards_refs(text)
        sec_refs = [r for r in refs if "36.331" in r.spec]
        sections = {r.section for r in sec_refs}
        assert "6.3.1" in sections
        assert "6.3.2" in sections


# ── Pattern 8: OMA DM ────────────────────────────────────────────────────────


class TestOmaDm:
    def test_omadm_spec(self):
        text = "per OMADM 2.0 section 7.1"
        refs = _extract_standards_refs(text)
        assert len(refs) >= 1
        oma = refs[0]
        assert "OMADM" in oma.spec
        assert oma.section == "7.1"

    def test_oma_dm_space(self):
        text = "OMA DM 1.3 section 5.2"
        refs = _extract_standards_refs(text)
        assert len(refs) >= 1
        assert "OMADM" in refs[0].spec


# ── Pattern 9: SPEC standalone fallback ──────────────────────────────────────


class TestSpecStandalone:
    def test_bare_3gpp_ts(self):
        text = "refer to 3GPP TS 38.321"
        refs = _extract_standards_refs(text)
        assert len(refs) == 1
        assert refs[0].spec == "3GPP TS 38.321"
        assert refs[0].section == ""
        assert refs[0].annex == ""
        assert refs[0].table == ""

    def test_bare_ts_prefix(self):
        text = "see TS 36.331 for details"
        refs = _extract_standards_refs(text)
        assert len(refs) == 1
        assert refs[0].spec == "3GPP TS 36.331"

    def test_bare_3gpp_tr(self):
        text = "see 3GPP TR 38.913"
        refs = _extract_standards_refs(text)
        assert len(refs) == 1
        assert refs[0].spec == "3GPP TS 38.913"

    def test_release_in_context(self):
        text = "Release 12, 3GPP TS 24.301 requirements"
        refs = _extract_standards_refs(text)
        r = _find(refs, "24.301")
        assert r is not None
        assert r.release == "Release 12"

    def test_space_typo_in_spec_number(self):
        """'38. 322' (space after dot) should still match."""
        text = "per 3GPP TS 38. 322"
        refs = _extract_standards_refs(text)
        assert len(refs) == 1
        assert refs[0].spec == "3GPP TS 38.322"

    def test_bare_3gpp_without_ts(self):
        """'3GPP 34.562' (no TS/TR) should match and normalize to 3GPP TS."""
        text = "as defined in 3GPP 34.562"
        refs = _extract_standards_refs(text)
        assert len(refs) == 1
        assert refs[0].spec == "3GPP TS 34.562"

    def test_bare_3gpp_with_section(self):
        text = "per 3GPP 24.301 section 5.5.1"
        refs = _extract_standards_refs(text)
        r = _find(refs, "24.301")
        assert r is not None
        assert r.spec == "3GPP TS 24.301"
        assert r.section == "5.5.1"


# ── Spec normalisation ────────────────────────────────────────────────────────


class TestSpecNormalisation:
    def test_tr_normalized_to_ts(self):
        text = "3GPP TR 38.913"
        refs = _extract_standards_refs(text)
        assert refs[0].spec == "3GPP TS 38.913"

    def test_ts_prefix_expands(self):
        text = "TS 24.301"
        refs = _extract_standards_refs(text)
        assert refs[0].spec == "3GPP TS 24.301"

    def test_hyphen_suffix_preserved(self):
        text = "3GPP TS 38.101-1"
        refs = _extract_standards_refs(text)
        assert refs[0].spec == "3GPP TS 38.101-1"

    def test_space_in_spec_stripped(self):
        """'38. 322' normalises to '38.322' (no space in output)."""
        text = "3GPP TS 38. 322"
        refs = _extract_standards_refs(text)
        assert refs[0].spec == "3GPP TS 38.322"


# ── Deduplication ────────────────────────────────────────────────────────────


class TestDeduplication:
    def test_same_ref_twice_deduped(self):
        text = "3GPP TS 24.301 and 3GPP TS 24.301"
        refs = _extract_standards_refs(text)
        specs = _specs(refs)
        assert specs.count("3GPP TS 24.301") == 1

    def test_different_sections_kept_separate(self):
        text = "Sections 5.1 and 5.2 of 3GPP TS 24.301"
        refs = _extract_standards_refs(text)
        sec_refs = [r for r in refs if "24.301" in r.spec]
        assert len(sec_refs) == 2

    def test_empty_text_returns_empty(self):
        assert _extract_standards_refs("") == []
        assert _extract_standards_refs(None) == []


# ── No false positives ────────────────────────────────────────────────────────


class TestNoFalsePositives:
    def test_plain_numbers_not_matched(self):
        text = "the device shall support 802.11ac and 802.11n"
        refs = _extract_standards_refs(text)
        # Plain 802.X numbers have no 3GPP/TS prefix → no match
        assert all("3GPP" in r.spec or "OMADM" in r.spec for r in refs)

    def test_version_number_without_spec_not_matched(self):
        text = "firmware version 15.6.0 shall be supported"
        refs = _extract_standards_refs(text)
        assert len(refs) == 0
