"""Tests for ConfigStore + Config-page wiring.

Covers:
  - SQLite CRUD round-trip with proper JSON encoding for typed values.
  - apply_to_caches() overlays stored values onto the cached
    LLMConfigFile / RetrievalConfig instances.
  - reapply_one() updates a single field on the cache.
  - Schema integrity — every section has at least one field; every
    field's category and kind is one of the allowed values.
  - find_field() / all_fields() helpers.
"""

from __future__ import annotations

import pytest

from core.src.web.config_db import ConfigStore
from core.src.web.config_schema import (
    CONFIG_SECTIONS,
    all_fields,
    find_field,
)


# ── Storage round-trips ────────────────────────────────────────


class TestConfigStoreCRUD:
    def test_set_and_get_string(self, tmp_path):
        cs = ConfigStore(tmp_path / "cfg.db")
        cs.set("llm", "llm_model", "gemma3:12b")
        assert cs.get("llm", "llm_model") == "gemma3:12b"

    def test_set_and_get_bool(self, tmp_path):
        cs = ConfigStore(tmp_path / "cfg.db")
        cs.set("llm", "skip_taxonomy", True)
        assert cs.get("llm", "skip_taxonomy") is True

    def test_set_and_get_int(self, tmp_path):
        cs = ConfigStore(tmp_path / "cfg.db")
        cs.set("pipeline", "top_k", 25)
        assert cs.get("pipeline", "top_k") == 25

    def test_set_and_get_float(self, tmp_path):
        cs = ConfigStore(tmp_path / "cfg.db")
        cs.set("retrieval", "gap_threshold", 0.07)
        # Round-trip must preserve float type
        v = cs.get("retrieval", "gap_threshold")
        assert isinstance(v, float)
        assert v == 0.07

    def test_get_missing_returns_none(self, tmp_path):
        cs = ConfigStore(tmp_path / "cfg.db")
        assert cs.get("llm", "nonexistent") is None

    def test_upsert_overwrites(self, tmp_path):
        cs = ConfigStore(tmp_path / "cfg.db")
        cs.set("llm", "llm_model", "first")
        cs.set("llm", "llm_model", "second")
        assert cs.get("llm", "llm_model") == "second"

    def test_get_module_returns_only_module_rows(self, tmp_path):
        cs = ConfigStore(tmp_path / "cfg.db")
        cs.set("llm", "llm_model", "gemma3:12b")
        cs.set("llm", "llm_provider", "ollama")
        cs.set("retrieval", "enable_grouping", True)
        llm_rows = cs.get_module("llm")
        assert llm_rows == {"llm_model": "gemma3:12b", "llm_provider": "ollama"}

    def test_get_all_returns_tuple_indexed(self, tmp_path):
        cs = ConfigStore(tmp_path / "cfg.db")
        cs.set("llm", "llm_model", "gemma3:12b")
        cs.set("retrieval", "gap_threshold", 0.05)
        all_rows = cs.get_all()
        assert all_rows[("llm", "llm_model")] == "gemma3:12b"
        assert all_rows[("retrieval", "gap_threshold")] == 0.05

    def test_delete_removes_row(self, tmp_path):
        cs = ConfigStore(tmp_path / "cfg.db")
        cs.set("llm", "llm_model", "gemma3:12b")
        cs.delete("llm", "llm_model")
        assert cs.get("llm", "llm_model") is None

    def test_persists_across_instances(self, tmp_path):
        path = tmp_path / "cfg.db"
        cs1 = ConfigStore(path)
        cs1.set("llm", "llm_model", "gemma3:12b")
        cs2 = ConfigStore(path)
        assert cs2.get("llm", "llm_model") == "gemma3:12b"


# ── Cache overlay ──────────────────────────────────────────────


class TestApplyToCaches:
    def test_apply_overlays_llm_field(self, tmp_path, monkeypatch):
        from core.src.env import config as env_cfg
        # Isolate from real config/llm.json
        empty = tmp_path / "llm.json"
        empty.write_text("{}")
        monkeypatch.setattr(env_cfg, "DEFAULT_LLM_CONFIG_PATH", empty)
        env_cfg._reset_llm_config_cache()
        try:
            cs = ConfigStore(tmp_path / "cfg.db")
            cs.set("llm", "llm_model", "qwen/qwen3-235b-a22b")
            cs.set("llm", "llm_provider", "openai-compatible")
            cs.apply_to_caches()
            cache = env_cfg._llm_config()
            assert cache.llm_model == "qwen/qwen3-235b-a22b"
            assert cache.llm_provider == "openai-compatible"
        finally:
            env_cfg._reset_llm_config_cache()

    def test_apply_overlays_retrieval_field(self, tmp_path, monkeypatch):
        from core.src.env import config as env_cfg
        empty = tmp_path / "retrieval.json"
        empty.write_text("{}")
        monkeypatch.setattr(env_cfg, "DEFAULT_RETRIEVAL_CONFIG_PATH", empty)
        env_cfg._reset_retrieval_config_cache()
        try:
            cs = ConfigStore(tmp_path / "cfg.db")
            cs.set("retrieval", "enable_grouping", True)
            cs.set("retrieval", "gap_threshold", 0.08)
            cs.apply_to_caches()
            cache = env_cfg._retrieval_config()
            assert cache.enable_grouping is True
            assert cache.gap_threshold == 0.08
        finally:
            env_cfg._reset_retrieval_config_cache()

    def test_unknown_module_silently_ignored(self, tmp_path):
        """Saving (module, key) that don't map to a cache field
        shouldn't raise — pipeline-module knobs are read directly
        from the store, not via apply_to_caches."""
        cs = ConfigStore(tmp_path / "cfg.db")
        cs.set("pipeline", "top_k", 25)
        cs.set("nonsense", "whatever", "x")
        # Doesn't raise
        cs.apply_to_caches()

    def test_reapply_one_updates_single_field(self, tmp_path, monkeypatch):
        from core.src.env import config as env_cfg
        empty = tmp_path / "llm.json"
        empty.write_text("{}")
        monkeypatch.setattr(env_cfg, "DEFAULT_LLM_CONFIG_PATH", empty)
        env_cfg._reset_llm_config_cache()
        try:
            cs = ConfigStore(tmp_path / "cfg.db")
            cs.set("llm", "llm_model", "model-a")
            cs.reapply_one("llm", "llm_model")
            assert env_cfg._llm_config().llm_model == "model-a"
        finally:
            env_cfg._reset_llm_config_cache()


# ── Schema integrity ───────────────────────────────────────────


class TestSchema:
    def test_at_least_one_section(self):
        assert len(CONFIG_SECTIONS) >= 1

    def test_every_section_has_fields(self):
        for s in CONFIG_SECTIONS:
            assert len(s.fields) >= 1

    def test_every_field_has_known_category(self):
        valid = {"feature", "value", "tunable"}
        for f in all_fields():
            assert f.category in valid, f"{f.module}.{f.key} has unknown category {f.category!r}"

    def test_every_field_has_known_kind(self):
        valid = {"bool", "string", "int", "float", "enum", "password"}
        for f in all_fields():
            assert f.kind in valid, f"{f.module}.{f.key} has unknown kind {f.kind!r}"

    def test_enum_fields_have_choices(self):
        for f in all_fields():
            if f.kind == "enum":
                assert len(f.choices) >= 2, f"{f.module}.{f.key} is enum but has < 2 choices"

    def test_bool_fields_are_features(self):
        """Conventionally, all toggles are in the 'feature' category."""
        for f in all_fields():
            if f.kind == "bool":
                assert f.category == "feature", (
                    f"{f.module}.{f.key} is bool but category={f.category!r}"
                )

    def test_find_field_returns_match(self):
        f = find_field("llm", "llm_provider")
        assert f is not None
        assert f.kind == "enum"

    def test_find_field_returns_none_on_miss(self):
        assert find_field("llm", "nonexistent") is None
