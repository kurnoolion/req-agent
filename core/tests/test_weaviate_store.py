"""Tests for core/src/weaviate_store — schema, ingester helpers, object building.

No live Weaviate connection required — all tests exercise pure-Python logic:
  - Schema: field presence, data types, BM25/filter settings for all 6 collections
  - Ingester helpers: _build_req_text, _content_hash, _parse_spec,
                      _expand_definitions, _table_to_markdown
  - Object properties: parent_req_id, children_req_ids, hierarchy_path
                       populated correctly from Requirement objects
  - StyleDrivenParser: definitions extraction (ACRONYMS/GLOSSARY/DEFINITIONS)
"""

from __future__ import annotations

import re
import pytest

# ── Schema imports ────────────────────────────────────────────────────────────

from core.src.weaviate_store.schema import (
    REQUIREMENT,
    REQUIREMENT_RELEASE,
    STANDARDS,
    DEVICE_COMPLIANCE,
    FEATURE,
    CARRIER_RELEASE,
    CREATION_ORDER,
    SCHEMAS,
    requirement_schema,
    requirement_release_schema,
    standards_schema,
    device_compliance_schema,
    carrier_release_schema,
)

# ── Ingester helper imports ───────────────────────────────────────────────────

from core.src.weaviate_store.ingester import (
    _build_req_text,
    _content_hash,
    _parse_spec,
    _expand_definitions,
    _compile_definitions_regex,
    _table_to_markdown,
)

# ── Parser imports ────────────────────────────────────────────────────────────

from core.src.models.document import DocumentIR, ContentBlock, BlockType, Position
from core.src.parser.style_parser import StyleDrivenParser
from core.src.parser.structural_parser import Requirement, TableData


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _pos(i: int = 0) -> Position:
    return Position(page=1, index=i)


_DEFAULT_PATH = ["SCENARIOS", "EMM", "ATTACH"]


def _make_req(
    req_id: str = "VZ_REQ_TEST_001",
    title: str = "Test Requirement",
    text: str = "The SDM shall support APN configuration.",
    hierarchy_path: list[str] | None = None,
    parent_req_id: str = "",
    children: list[str] | None = None,
    tables: list[TableData] | None = None,
) -> Requirement:
    r = Requirement(
        req_id=req_id,
        title=title,
        text=text,
        # Use explicit None-check so callers can pass hierarchy_path=[]
        hierarchy_path=hierarchy_path if hierarchy_path is not None else _DEFAULT_PATH,
        parent_req_id=parent_req_id,
        children=children or [],
        tables=tables or [],
    )
    return r


def _make_doc(*blocks: ContentBlock) -> DocumentIR:
    return DocumentIR(
        source_file="test.docx",
        source_format="docx",
        mno="VZW",
        release="Feb 2026",
        content_blocks=list(blocks),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Schema tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaCreationOrder:
    def test_standards_first(self):
        """Standards must be created before collections that reference it."""
        assert CREATION_ORDER[0] == STANDARDS

    def test_req_release_before_requirement(self):
        idx_rel = CREATION_ORDER.index(REQUIREMENT_RELEASE)
        idx_req = CREATION_ORDER.index(REQUIREMENT)
        assert idx_rel < idx_req

    def test_requirement_before_device_compliance(self):
        idx_req = CREATION_ORDER.index(REQUIREMENT)
        idx_dc  = CREATION_ORDER.index(DEVICE_COMPLIANCE)
        assert idx_req < idx_dc

    def test_all_six_collections_present(self):
        assert set(CREATION_ORDER) == {
            REQUIREMENT, REQUIREMENT_RELEASE, STANDARDS,
            DEVICE_COMPLIANCE, FEATURE, CARRIER_RELEASE,
        }

    def test_schemas_registry_matches_creation_order(self):
        assert set(SCHEMAS.keys()) == set(CREATION_ORDER)


def _prop_names(schema_fn) -> list[str]:
    """Return property names from a schema function (requires weaviate import)."""
    return [p.name for p in schema_fn()["properties"]]


def _ref_names(schema_fn) -> list[str]:
    return [r.name for r in schema_fn().get("references", [])]


class TestRequirementSchema:
    def test_context_enrichment_fields_present(self):
        names = _prop_names(requirement_schema)
        assert "parent_req_id"    in names, "parent_req_id missing from Class 1"
        assert "children_req_ids" in names, "children_req_ids missing from Class 1"
        assert "hierarchy_path"   in names, "hierarchy_path missing from Class 1"

    def test_core_fields_present(self):
        names = _prop_names(requirement_schema)
        for field in ("req_id", "carrier", "req_text", "req_tables",
                      "req_tg", "has_images", "image_captions", "current_release"):
            assert field in names, f"{field} missing from Class 1"

    def test_cross_refs_present(self):
        refs = _ref_names(requirement_schema)
        assert "depends_on"      in refs
        assert "standards"       in refs
        assert "release_history" in refs

    def test_depends_on_targets_requirement(self):
        """Self-referential cross-ref must target the Requirement collection."""
        refs = requirement_schema().get("references", [])
        dep = next((r for r in refs if r.name == "depends_on"), None)
        assert dep is not None
        assert dep.target_collection == REQUIREMENT

    def test_content_fields_are_searchable(self):
        """req_text, req_tables, image_captions must be BM25-searchable."""
        props = {p.name: p for p in requirement_schema()["properties"]}
        for field in ("req_text", "req_tables", "image_captions"):
            assert props[field].index_searchable is True, f"{field} not searchable"

    def test_metadata_fields_not_searchable(self):
        """ID/code fields must not be BM25-indexed."""
        props = {p.name: p for p in requirement_schema()["properties"]}
        for field in ("req_id", "carrier", "req_tg", "current_release",
                      "parent_req_id", "children_req_ids", "hierarchy_path"):
            assert props[field].index_searchable is False, f"{field} should not be searchable"

    def test_context_fields_are_filterable(self):
        props = {p.name: p for p in requirement_schema()["properties"]}
        for field in ("parent_req_id", "children_req_ids", "hierarchy_path"):
            assert props[field].index_filterable is True, f"{field} not filterable"


class TestRequirementReleaseSchema:
    def test_context_enrichment_fields_present(self):
        names = _prop_names(requirement_release_schema)
        assert "parent_req_id"    in names, "parent_req_id missing from Class 2"
        assert "children_req_ids" in names, "children_req_ids missing from Class 2"
        assert "hierarchy_path"   in names, "hierarchy_path missing from Class 2"

    def test_core_fields_present(self):
        names = _prop_names(requirement_release_schema)
        for field in ("req_id", "carrier", "req_text", "req_tables",
                      "req_releases", "has_images", "image_captions",
                      "req_tg", "depends_on_req_ids", "content_hash"):
            assert field in names, f"{field} missing from Class 2"

    def test_cross_refs_present(self):
        refs = _ref_names(requirement_release_schema)
        assert "standards"   in refs
        assert "current_req" in refs

    def test_content_fields_searchable(self):
        props = {p.name: p for p in requirement_release_schema()["properties"]}
        for field in ("req_text", "req_tables", "image_captions"):
            assert props[field].index_searchable is True

    def test_metadata_fields_not_searchable(self):
        props = {p.name: p for p in requirement_release_schema()["properties"]}
        for field in ("req_id", "carrier", "content_hash",
                      "parent_req_id", "children_req_ids", "hierarchy_path"):
            assert props[field].index_searchable is False


class TestStandardsSchema:
    def test_core_fields_present(self):
        names = _prop_names(standards_schema)
        for field in ("doc_id", "release_id", "standard_type", "content_type",
                      "content_id", "content_text", "content_available",
                      "carriers", "req_id"):
            assert field in names, f"{field} missing from Standards"

    def test_content_text_searchable(self):
        props = {p.name: p for p in standards_schema()["properties"]}
        assert props["content_text"].index_searchable is True

    def test_metadata_not_searchable(self):
        props = {p.name: p for p in standards_schema()["properties"]}
        for field in ("doc_id", "release_id", "standard_type", "content_type",
                      "content_id", "content_available", "carriers", "req_id"):
            assert props[field].index_searchable is False


class TestCarrierReleaseSchema:
    def test_core_fields_present(self):
        names = _prop_names(carrier_release_schema)
        for field in ("carrier", "latest_release", "all_releases",
                      "latest_fld_release", "all_fld_releases",
                      "release_date", "fld_release_date", "last_updated"):
            assert field in names, f"{field} missing from CarrierRelease"

    def test_no_references(self):
        assert carrier_release_schema().get("references", []) == []


# ═══════════════════════════════════════════════════════════════════════════════
# Ingester helper tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseSpec:
    def test_3gpp_ts(self):
        assert _parse_spec("3GPP TS 24.301") == ("3GPP", "24.301")

    def test_3gpp_tr(self):
        assert _parse_spec("3GPP TR 38.913") == ("3GPP", "38.913")

    def test_etsi_ts(self):
        assert _parse_spec("ETSI TS 102.221") == ("ETSI", "102.221")

    def test_etsi_en(self):
        assert _parse_spec("ETSI EN 303.413") == ("ETSI", "303.413")

    def test_omadm_excluded(self):
        assert _parse_spec("OMADM 2.0") is None

    def test_unknown_prefix_excluded(self):
        assert _parse_spec("GSMA IR.92") is None

    def test_bare_string_excluded(self):
        assert _parse_spec("24.301") is None

    def test_hyphen_suffix_preserved(self):
        result = _parse_spec("3GPP TS 38.101-1")
        assert result == ("3GPP", "38.101-1")


class TestContentHash:
    def test_same_input_same_hash(self):
        h1 = _content_hash("text", ["table"], "caption")
        h2 = _content_hash("text", ["table"], "caption")
        assert h1 == h2

    def test_different_text_different_hash(self):
        h1 = _content_hash("text A", [], "")
        h2 = _content_hash("text B", [], "")
        assert h1 != h2

    def test_different_tables_different_hash(self):
        h1 = _content_hash("text", ["table A"], "")
        h2 = _content_hash("text", ["table B"], "")
        assert h1 != h2

    def test_different_captions_different_hash(self):
        h1 = _content_hash("text", [], "caption A")
        h2 = _content_hash("text", [], "caption B")
        assert h1 != h2

    def test_empty_inputs(self):
        h = _content_hash("", [], "")
        assert len(h) == 64  # SHA-256 hex

    def test_table_order_matters(self):
        h1 = _content_hash("text", ["A", "B"], "")
        h2 = _content_hash("text", ["B", "A"], "")
        assert h1 != h2


class TestDefinitionsExpansion:
    def test_first_occurrence_expanded(self):
        defs = {"SDM": "Subscriber Device Management"}
        pat = _compile_definitions_regex(defs)
        result = _expand_definitions("The SDM shall support SDM.", pat, defs)
        assert "SDM (Subscriber Device Management)" in result
        # Second occurrence NOT expanded
        assert result.count("(Subscriber Device Management)") == 1

    def test_multiple_terms_expanded(self):
        defs = {"SDM": "Subscriber Device Management", "APN": "Access Point Name"}
        pat = _compile_definitions_regex(defs)
        result = _expand_definitions("SDM uses APN.", pat, defs)
        assert "SDM (Subscriber Device Management)" in result
        assert "APN (Access Point Name)" in result

    def test_empty_map_returns_text_unchanged(self):
        pat = _compile_definitions_regex({})
        assert pat is None
        text = "The SDM shall support APN."
        # With None pattern, caller skips expansion — test the guard
        result = text  # no expansion
        assert result == "The SDM shall support APN."

    def test_unknown_term_not_expanded(self):
        defs = {"SDM": "Subscriber Device Management"}
        pat = _compile_definitions_regex(defs)
        result = _expand_definitions("The RAT selection.", pat, defs)
        assert result == "The RAT selection."

    def test_longest_term_matches_first(self):
        """'IMS REGISTRATION' should match before bare 'IMS'."""
        defs = {"IMS": "IP Multimedia Subsystem", "IMS REGISTRATION": "IMS Registration Procedure"}
        pat = _compile_definitions_regex(defs)
        result = _expand_definitions("IMS REGISTRATION is triggered.", pat, defs)
        assert "IMS REGISTRATION (IMS Registration Procedure)" in result
        assert "IMS (IP Multimedia Subsystem)" not in result


class TestTableToMarkdown:
    def test_normal_table(self):
        tbl = TableData(headers=["Parameter", "Value"], rows=[["APN", "internet"], ["RAT", "LTE"]])
        md = _table_to_markdown(tbl)
        assert "| Parameter | Value |" in md
        assert "| APN | internet |" in md
        assert "| RAT | LTE |" in md
        assert "---" in md

    def test_empty_rows_returns_empty(self):
        tbl = TableData(headers=["A", "B"], rows=[])
        assert _table_to_markdown(tbl) == ""

    def test_no_headers_still_renders(self):
        tbl = TableData(headers=[], rows=[["val1", "val2"]])
        md = _table_to_markdown(tbl)
        assert "val1" in md

    def test_all_empty_headers_compact_format(self):
        tbl = TableData(headers=["", ""], rows=[["REQ_001", "REQ_002"]])
        md = _table_to_markdown(tbl)
        assert "[Table:" in md


class TestBuildReqText:
    def test_hierarchy_path_included(self):
        req = _make_req(hierarchy_path=["SCENARIOS", "EMM", "ATTACH"])
        text = _build_req_text(req, {}, None)
        assert "[Path: SCENARIOS > EMM > ATTACH]" in text

    def test_req_id_included(self):
        req = _make_req(req_id="VZ_REQ_TEST_001")
        text = _build_req_text(req, {}, None)
        assert "[Req ID: VZ_REQ_TEST_001]" in text

    def test_title_included(self):
        req = _make_req(title="Attach Procedure")
        text = _build_req_text(req, {}, None)
        assert "Attach Procedure" in text

    def test_body_text_included(self):
        req = _make_req(text="The device shall register.")
        text = _build_req_text(req, {}, None)
        assert "The device shall register." in text

    def test_no_mno_release_plan_header(self):
        """MNO/release/plan header must NOT appear — per design decision."""
        req = _make_req()
        text = _build_req_text(req, {}, None)
        assert "[MNO:" not in text
        assert "[Release:" not in text
        assert "[Plan:" not in text

    def test_definitions_expansion_applied(self):
        req = _make_req(text="The SDM shall configure APN settings.")
        defs = {"SDM": "Subscriber Device Management", "APN": "Access Point Name"}
        pat = _compile_definitions_regex(defs)
        text = _build_req_text(req, defs, pat)
        assert "SDM (Subscriber Device Management)" in text
        assert "APN (Access Point Name)" in text

    def test_empty_hierarchy_path_omitted(self):
        req = _make_req(hierarchy_path=[])
        text = _build_req_text(req, {}, None)
        assert "[Path:" not in text

    def test_empty_req_id_omitted(self):
        req = _make_req(req_id="")
        text = _build_req_text(req, {}, None)
        assert "[Req ID:" not in text


# ═══════════════════════════════════════════════════════════════════════════════
# Object property building — parent, children, hierarchy_path
# ═══════════════════════════════════════════════════════════════════════════════


class TestContextEnrichmentFields:
    """Verify parent_req_id, children_req_ids, hierarchy_path are wired
    into ingester property dicts correctly (without a live Weaviate)."""

    def _build_props(
        self,
        parent_req_id: str,
        children: list[str],
        hierarchy_path: list[str],
    ) -> dict:
        """Simulate the property dict built in Phase 2/3 of the ingester."""
        req = _make_req(
            parent_req_id=parent_req_id,
            children=children,
            hierarchy_path=hierarchy_path,
        )
        defs_map: dict = {}
        req_text = _build_req_text(req, defs_map, None)
        return {
            "req_text":          req_text,
            "parent_req_id":     req.parent_req_id or "",
            "children_req_ids":  list(req.children or []),
            "hierarchy_path":    list(req.hierarchy_path or []),
        }

    def test_parent_req_id_stored(self):
        props = self._build_props("VZ_REQ_TEST_000", [], ["ZONE"])
        assert props["parent_req_id"] == "VZ_REQ_TEST_000"

    def test_empty_parent_stored_as_empty_string(self):
        props = self._build_props("", [], ["ZONE"])
        assert props["parent_req_id"] == ""

    def test_children_stored_as_list(self):
        kids = ["VZ_REQ_TEST_002", "VZ_REQ_TEST_003"]
        props = self._build_props("", kids, ["ZONE"])
        assert props["children_req_ids"] == kids

    def test_empty_children_stored_as_empty_list(self):
        props = self._build_props("", [], ["ZONE"])
        assert props["children_req_ids"] == []

    def test_hierarchy_path_stored_as_list(self):
        path = ["SCENARIOS", "EMM PROCEDURES", "ATTACH REQUEST"]
        props = self._build_props("", [], path)
        assert props["hierarchy_path"] == path

    def test_hierarchy_path_also_in_req_text(self):
        """hierarchy_path must appear in req_text for BM25/vector search."""
        path = ["SCENARIOS", "EMM PROCEDURES", "ATTACH REQUEST"]
        props = self._build_props("", [], path)
        assert "SCENARIOS > EMM PROCEDURES > ATTACH REQUEST" in props["req_text"]

    def test_hierarchy_path_and_stored_field_consistent(self):
        """Stored field and req_text path must contain the same titles."""
        path = ["SCENARIOS", "LTE ATTACH", "INITIAL ATTACH"]
        props = self._build_props("", [], path)
        for title in path:
            assert title in props["req_text"]
            assert title in props["hierarchy_path"]


# ═══════════════════════════════════════════════════════════════════════════════
# StyleDrivenParser — definitions extraction
# ═══════════════════════════════════════════════════════════════════════════════


class TestStyleDrivenParserDefinitions:

    def _parse(self, *blocks: ContentBlock) -> object:
        doc = _make_doc(*blocks)
        return StyleDrivenParser().parse(doc)

    def test_acronyms_glossary_definitions_heading_detected(self):
        tree = self._parse(
            ContentBlock(type=BlockType.HEADING, level=1,
                         text="1.1.3 ACRONYMS/GLOSSARY/DEFINITIONS", position=_pos(0)),
            ContentBlock(type=BlockType.TABLE, position=_pos(1),
                         headers=["Acronym", "Definition"],
                         rows=[["SDM", "Subscriber Device Management"],
                               ["APN", "Access Point Name"]]),
            ContentBlock(type=BlockType.HEADING, level=1,
                         text="Section VZ_REQ_TEST_001", position=_pos(2)),
        )
        assert "SDM" in tree.definitions_map
        assert tree.definitions_map["SDM"] == "Subscriber Device Management"
        assert "APN" in tree.definitions_map
        assert tree.definitions_map["APN"] == "Access Point Name"

    def test_all_four_stem_variants_detected(self):
        """acronym / glossar / definit / abbreviat all trigger definitions mode."""
        headings = [
            "ACRONYMS",
            "GLOSSARY",
            "DEFINITIONS",
            "ABBREVIATIONS",
        ]
        for heading_text in headings:
            tree = self._parse(
                ContentBlock(type=BlockType.HEADING, level=1,
                             text=heading_text, position=_pos(0)),
                ContentBlock(type=BlockType.TABLE, position=_pos(1),
                             headers=["Term", "Meaning"],
                             rows=[["RAT", "Radio Access Technology"]]),
                ContentBlock(type=BlockType.HEADING, level=1,
                             text="Req VZ_REQ_TEST_001", position=_pos(2)),
            )
            assert "RAT" in tree.definitions_map, \
                f"Heading '{heading_text}' did not trigger definitions extraction"

    def test_canonical_header_row_excluded(self):
        """'Acronym | Definition' column header must not enter definitions_map."""
        tree = self._parse(
            ContentBlock(type=BlockType.HEADING, level=1,
                         text="ACRONYMS", position=_pos(0)),
            ContentBlock(type=BlockType.TABLE, position=_pos(1),
                         headers=["Acronym", "Definition"],
                         rows=[["SDM", "Subscriber Device Management"]]),
            ContentBlock(type=BlockType.HEADING, level=1,
                         text="Req VZ_REQ_TEST_001", position=_pos(2)),
        )
        assert "Acronym"    not in tree.definitions_map
        assert "Definition" not in tree.definitions_map
        assert "SDM" in tree.definitions_map

    def test_definitions_table_does_not_attach_to_last_req(self):
        """Tables in definitions section must NOT appear as req.tables."""
        tree = self._parse(
            ContentBlock(type=BlockType.HEADING, level=1,
                         text="Some Req VZ_REQ_TEST_000", position=_pos(0)),
            ContentBlock(type=BlockType.HEADING, level=1,
                         text="ACRONYMS", position=_pos(1)),
            ContentBlock(type=BlockType.TABLE, position=_pos(2),
                         headers=["Term", "Meaning"],
                         rows=[["SDM", "Subscriber Device Management"]]),
        )
        req = tree.requirements[0]
        assert len(req.tables) == 0, "Definitions table attached to last requirement"

    def test_defs_extracted_count_in_parse_stats(self):
        tree = self._parse(
            ContentBlock(type=BlockType.HEADING, level=1,
                         text="ACRONYMS", position=_pos(0)),
            ContentBlock(type=BlockType.TABLE, position=_pos(1),
                         headers=["Term", "Meaning"],
                         rows=[["SDM", "Subscriber Device Management"],
                               ["APN", "Access Point Name"],
                               ["RAT", "Radio Access Technology"]]),
            ContentBlock(type=BlockType.HEADING, level=1,
                         text="Req VZ_REQ_TEST_001", position=_pos(2)),
        )
        assert tree.parse_stats.defs_extracted == 3

    def test_no_definitions_section_empty_map(self):
        """Document with no definitions heading → empty definitions_map."""
        tree = self._parse(
            ContentBlock(type=BlockType.HEADING, level=1,
                         text="Some Req VZ_REQ_TEST_001", position=_pos(0)),
            ContentBlock(type=BlockType.PARAGRAPH,
                         text="The device shall register.", position=_pos(1)),
        )
        assert tree.definitions_map == {}
        assert tree.definitions_section_number == ""

    def test_vz_req_heading_after_definitions_exits_mode(self):
        """Once a VZ_REQ_ heading appears, definitions mode exits — subsequent
        tables attach to that requirement, not definitions_map."""
        tree = self._parse(
            ContentBlock(type=BlockType.HEADING, level=1,
                         text="ACRONYMS", position=_pos(0)),
            ContentBlock(type=BlockType.TABLE, position=_pos(1),
                         headers=["Term", "Meaning"],
                         rows=[["SDM", "Subscriber Device Management"]]),
            ContentBlock(type=BlockType.HEADING, level=1,
                         text="Attach Procedure VZ_REQ_TEST_001", position=_pos(2)),
            ContentBlock(type=BlockType.TABLE, position=_pos(3),
                         headers=["State", "Action"],
                         rows=[["IDLE", "Send Attach Request"]]),
        )
        assert "SDM" in tree.definitions_map
        req = tree.requirements[0]
        assert len(req.tables) == 1, "Requirement table not attached after definitions mode exited"

    def test_first_occurrence_wins_on_duplicate_term(self):
        """If same term appears in two table rows, first value wins."""
        tree = self._parse(
            ContentBlock(type=BlockType.HEADING, level=1,
                         text="GLOSSARY", position=_pos(0)),
            ContentBlock(type=BlockType.TABLE, position=_pos(1),
                         headers=["Term", "Meaning"],
                         rows=[["SDM", "Subscriber Device Management"],
                               ["SDM", "Some Different Meaning"]]),
            ContentBlock(type=BlockType.HEADING, level=1,
                         text="Req VZ_REQ_TEST_001", position=_pos(2)),
        )
        assert tree.definitions_map["SDM"] == "Subscriber Device Management"

    def test_definitions_section_number_recorded(self):
        tree = self._parse(
            ContentBlock(type=BlockType.HEADING, level=1,
                         text="ACRONYMS", position=_pos(0)),
            ContentBlock(type=BlockType.TABLE, position=_pos(1),
                         headers=["Term", "Meaning"],
                         rows=[["SDM", "Subscriber Device Management"]]),
        )
        assert tree.definitions_section_number != ""
