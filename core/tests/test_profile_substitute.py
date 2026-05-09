"""Tests for profile placeholder substitution [D-062]."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.src.profiler.profile_schema import (
    CrossReferencePatterns,
    DocumentProfile,
    HeadingDetection,
    RequirementIdPattern,
)
from core.src.profiler.profile_substitute import (
    GENERIC_PLACEHOLDERS,
    _normalize_mapping,
    find_mapping_file,
    load_substituted_profile,
    substitute_placeholders,
)


# ---------------------------------------------------------------------------
# substitute_placeholders — core rules
# ---------------------------------------------------------------------------

class TestSubstituteSpecific:
    def test_specific_placeholder_replaced_with_escaped_value(self):
        p = DocumentProfile(
            requirement_id=RequirementIdPattern(pattern="<MNO0>_REQ_FOO_\\d+"),
        )
        out = substitute_placeholders(p, {"MNO0": "VZ"})
        assert out.requirement_id.pattern == "VZ_REQ_FOO_\\d+"

    def test_specific_value_with_regex_metacharacters_is_escaped(self):
        # If the mapped value contains regex metacharacters they must be
        # escaped — otherwise a value like "foo.bar" would match
        # "fooxbar" silently.
        p = DocumentProfile(
            requirement_id=RequirementIdPattern(pattern="<MNO0>_REQ"),
        )
        out = substitute_placeholders(p, {"MNO0": "V.Z"})
        assert out.requirement_id.pattern == "V\\.Z_REQ"

    def test_longer_specific_keys_substitute_first(self):
        # `<MNO0_ALIAS>` must substitute before `<MNO0>` — otherwise the
        # short prefix consumes the inner string and leaves `_ALIAS>`
        # dangling as garbage.
        p = DocumentProfile(
            requirement_id=RequirementIdPattern(pattern="<MNO0_ALIAS>_<MNO0>"),
        )
        out = substitute_placeholders(p, {"MNO0": "VZ", "MNO0_ALIAS": "VZW"})
        assert out.requirement_id.pattern == "VZW_VZ"


class TestSubstituteGeneric:
    def test_mno_generic_to_letter_class(self):
        p = DocumentProfile(
            requirement_id=RequirementIdPattern(pattern="<MNO>_REQ"),
        )
        out = substitute_placeholders(p, {})
        assert out.requirement_id.pattern == GENERIC_PLACEHOLDERS["<MNO>"] + "_REQ"

    def test_plan_generic_to_alnum_class(self):
        p = DocumentProfile(
            requirement_id=RequirementIdPattern(pattern="VZ_REQ_<PLAN>_\\d+"),
        )
        out = substitute_placeholders(p, {})
        assert out.requirement_id.pattern == "VZ_REQ_[A-Z0-9_]+_\\d+"

    def test_digits_generic_to_digit_quantifier(self):
        p = DocumentProfile(
            requirement_id=RequirementIdPattern(pattern="<MNO0>_REQ_<PLAN>_<DIGITS>"),
        )
        out = substitute_placeholders(p, {"MNO0": "VZ"})
        assert out.requirement_id.pattern == r"VZ_REQ_[A-Z0-9_]+_\d+"

    def test_specific_takes_precedence_over_generic_with_same_root(self):
        # `<PLAN0>` is in the mapping (specific); `<PLAN>` (generic) should
        # not steal the substitution — both forms can appear in the same
        # pattern.
        p = DocumentProfile(
            requirement_id=RequirementIdPattern(pattern="<MNO0>_REQ_(<PLAN0>|<PLAN>)"),
        )
        out = substitute_placeholders(p, {"MNO0": "VZ", "PLAN0": "PLANX"})
        # <PLAN0> resolves to PLANX; <PLAN> falls through to the generic class.
        assert out.requirement_id.pattern == "VZ_REQ_(PLANX|[A-Z0-9_]+)"


class TestSubstituteAcrossFields:
    def test_walks_every_regex_field(self):
        p = DocumentProfile(
            heading_detection=HeadingDetection(
                numbering_pattern="<DIGITS>",
                priority_marker_pattern="<MNO0>:",
            ),
            requirement_id=RequirementIdPattern(pattern="<MNO0>_REQ_<PLAN>_<DIGITS>"),
            cross_reference_patterns=CrossReferencePatterns(
                requirement_id_refs="<MNO0>_REQ_<PLAN>_<DIGITS>",
                internal_section_refs="See <MNO0> §<DIGITS>",
                standards_citations=["<MNO>\\s+\\w+"],
            ),
        )
        p.reference_list_section_pattern = "<MNO0> bibliography"
        p.reference_list_entry_pattern = "<DIGITS>\\s+(.+)"
        out = substitute_placeholders(p, {"MNO0": "VZ"})

        assert out.heading_detection.numbering_pattern == r"\d+"
        assert out.heading_detection.priority_marker_pattern == "VZ:"
        assert out.requirement_id.pattern == r"VZ_REQ_[A-Z0-9_]+_\d+"
        assert out.cross_reference_patterns.requirement_id_refs == r"VZ_REQ_[A-Z0-9_]+_\d+"
        assert out.cross_reference_patterns.internal_section_refs == r"See VZ §\d+"
        assert out.cross_reference_patterns.standards_citations == [r"[A-Z]{2,4}\s+\w+"]
        assert out.reference_list_section_pattern == "VZ bibliography"
        assert out.reference_list_entry_pattern == r"\d+\s+(.+)"

    def test_input_profile_not_mutated(self):
        p = DocumentProfile(
            requirement_id=RequirementIdPattern(pattern="<MNO0>_REQ"),
        )
        substitute_placeholders(p, {"MNO0": "VZ"})
        assert p.requirement_id.pattern == "<MNO0>_REQ"


class TestUnresolvedPlaceholderWarns:
    def test_unknown_placeholder_left_in_place(self, caplog):
        # `<UNKNOWN>` isn't in the mapping and isn't a generic — leave it
        # alone but log a warning so the user can fix the mapping.
        import logging
        p = DocumentProfile(
            requirement_id=RequirementIdPattern(pattern="<UNKNOWN>_REQ"),
        )
        with caplog.at_level(logging.WARNING):
            out = substitute_placeholders(p, {})
        assert out.requirement_id.pattern == "<UNKNOWN>_REQ"
        assert any("UNKNOWN" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# _normalize_mapping — both on-disk shapes accepted
# ---------------------------------------------------------------------------

class TestNormalizeMapping:
    def test_snapshot_shape_passthrough(self):
        # `{"MNO0": "VZ"}` — bare placeholder name, real value (snapshot shape)
        assert _normalize_mapping({"MNO0": "VZ", "PLAN0": "PLANX"}) == {
            "MNO0": "VZ", "PLAN0": "PLANX",
        }

    def test_live_shape_inverted_correctly(self):
        # `{"<MNO0>": "VZ"}` — bracketed placeholder, real value (snapshot shape with brackets)
        assert _normalize_mapping({"<MNO0>": "VZ"}) == {"MNO0": "VZ"}

    def test_cline_forward_redaction_shape_inverted(self):
        # `{"VZ": "<MNO0>"}` — real value → placeholder (Cline live forward-redaction shape)
        assert _normalize_mapping({"VZ": "<MNO0>", "PLANX": "<PLAN0>"}) == {
            "MNO0": "VZ", "PLAN0": "PLANX",
        }

    def test_mixed_shapes_both_handled(self):
        result = _normalize_mapping({
            "<MNO0>": "VZ",        # bracketed key
            "PLANX": "<PLAN0>",    # live forward
            "REL0": "Feb2026",     # snapshot bare
        })
        assert result == {"MNO0": "VZ", "PLAN0": "PLANX", "REL0": "Feb2026"}


# ---------------------------------------------------------------------------
# find_mapping_file — discovery chain
# ---------------------------------------------------------------------------

class TestFindMappingFile:
    def test_snapshot_takes_priority_over_env_dir(self, tmp_path):
        project = tmp_path / "project"
        (project / "customizations" / "mappings").mkdir(parents=True)
        (project / "customizations" / "profiles").mkdir(parents=True)
        snapshot = project / "customizations" / "mappings" / "bs_abc.json"
        snapshot.write_text("{}")
        profile_path = project / "customizations" / "profiles" / "bs_abc.json"
        profile_path.write_text("{}")

        env_dir = tmp_path / "env"
        (env_dir / "state").mkdir(parents=True)
        (env_dir / "state" / "cline-mapping.json").write_text("{}")

        result = find_mapping_file(profile_path, env_dir=env_dir)
        assert result == snapshot

    def test_falls_back_to_env_dir(self, tmp_path):
        project = tmp_path / "project"
        (project / "customizations" / "profiles").mkdir(parents=True)
        (project / "customizations" / "mappings").mkdir(parents=True)
        profile_path = project / "customizations" / "profiles" / "bs_xyz.json"
        profile_path.write_text("{}")

        env_dir = tmp_path / "env"
        (env_dir / "state").mkdir(parents=True)
        cline = env_dir / "state" / "cline-mapping.json"
        cline.write_text("{}")

        result = find_mapping_file(profile_path, env_dir=env_dir)
        assert result == cline

    def test_returns_none_when_no_mapping_anywhere(self, tmp_path):
        project = tmp_path / "project"
        (project / "customizations" / "profiles").mkdir(parents=True)
        profile_path = project / "customizations" / "profiles" / "bs_q.json"
        profile_path.write_text("{}")
        assert find_mapping_file(profile_path, env_dir=None) is None

    def test_env_dir_not_provided_skips_fallback(self, tmp_path):
        project = tmp_path / "project"
        (project / "customizations" / "profiles").mkdir(parents=True)
        profile_path = project / "customizations" / "profiles" / "bs_q.json"
        profile_path.write_text("{}")
        assert find_mapping_file(profile_path) is None


# ---------------------------------------------------------------------------
# load_substituted_profile — end-to-end
# ---------------------------------------------------------------------------

class TestLoadSubstitutedProfile:
    def _scaffold_project(self, tmp_path: Path) -> tuple[Path, Path]:
        project = tmp_path / "project"
        (project / "customizations" / "profiles").mkdir(parents=True)
        (project / "customizations" / "mappings").mkdir(parents=True)
        profile = DocumentProfile(
            profile_name="bs_test",
            requirement_id=RequirementIdPattern(pattern="<MNO0>_REQ_<PLAN>_\\d+"),
        )
        profile_path = project / "customizations" / "profiles" / "bs_test.json"
        profile.save_json(profile_path)
        return project, profile_path

    def test_with_snapshot_substitutes(self, tmp_path):
        project, profile_path = self._scaffold_project(tmp_path)
        snapshot = project / "customizations" / "mappings" / "bs_test.json"
        snapshot.write_text(json.dumps({
            "version": 1, "bootstrap_id": "bs_test",
            "mappings": {"MNO0": "VZ"},
        }))
        out = load_substituted_profile(profile_path)
        assert out.requirement_id.pattern == r"VZ_REQ_[A-Z0-9_]+_\d+"

    def test_with_env_dir_fallback_substitutes(self, tmp_path):
        project, profile_path = self._scaffold_project(tmp_path)
        # No customizations/mappings/<id>.json
        env_dir = tmp_path / "env"
        (env_dir / "state").mkdir(parents=True)
        # Cline live shape: real → placeholder
        (env_dir / "state" / "cline-mapping.json").write_text(json.dumps({
            "version": 1, "mappings": {"VZ": "<MNO0>"},
        }))
        out = load_substituted_profile(profile_path, env_dir=env_dir)
        assert out.requirement_id.pattern == r"VZ_REQ_[A-Z0-9_]+_\d+"

    def test_no_mapping_returns_profile_unchanged(self, tmp_path):
        # Public-corpus case (vzw_oa_profile.json analogue): no mapping
        # anywhere → load returns the profile with placeholders/strings
        # exactly as written. Wildcards (<PLAN>) still resolve to their
        # generic class because that's mapping-independent.
        project, profile_path = self._scaffold_project(tmp_path)
        out = load_substituted_profile(profile_path, env_dir=None)
        # Specific placeholder UNCHANGED (no mapping)
        assert "<MNO0>" in out.requirement_id.pattern
        # No accidental wildcard substitution either
        assert "<PLAN>" in out.requirement_id.pattern

    def test_committed_bs_d7a2c81f_loads(self):
        # Sanity: the placeholdered profile we ship in this commit loads
        # cleanly and exposes the expected placeholders.
        from core.src.profiler.profile_schema import DocumentProfile
        path = Path("customizations/profiles/bs_d7a2c81f.json")
        if not path.exists():
            pytest.skip("bs_d7a2c81f.json not in tree")
        profile = DocumentProfile.load_json(path)
        assert profile.profile_name == "bs_d7a2c81f"
        assert "<MNO0>" in profile.requirement_id.pattern
        assert "<PLAN>" in profile.requirement_id.pattern
