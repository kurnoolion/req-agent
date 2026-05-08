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
        valid = {"bool", "string", "int", "float", "enum", "password",
                 "dict_by_query_type"}
        for f in all_fields():
            assert f.kind in valid, f"{f.module}.{f.key} has unknown kind {f.kind!r}"

    def test_dict_by_query_type_fields_have_value_kind(self):
        """Per-type table fields must declare what each cell holds so
        the form can coerce values correctly on save."""
        valid_value_kinds = {"float", "int", "bool", "string"}
        for f in all_fields():
            if f.kind == "dict_by_query_type":
                assert f.value_kind in valid_value_kinds, (
                    f"{f.module}.{f.key} kind=dict_by_query_type but "
                    f"value_kind={f.value_kind!r}"
                )

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


# ── Route smoke tests ──────────────────────────────────────────


class TestConfigRouteRenders:
    """End-to-end render of /config catches template/route regressions
    (e.g. Jinja attr/item lookup collisions like `section.values`)."""

    def _client(self, tmp_path, monkeypatch, with_db=True):
        from fastapi.testclient import TestClient
        if with_db:
            monkeypatch.setenv("NORA_CONFIG_DB", str(tmp_path / "cfg.db"))
        else:
            monkeypatch.delenv("NORA_CONFIG_DB", raising=False)
        # Set ENV_DIR to a tmp path; web app needs it.
        monkeypatch.setenv("ENV_DIR", str(tmp_path))
        # Re-import the app module so config picks up env vars.
        import importlib
        import core.src.web.app as app_mod
        importlib.reload(app_mod)
        return TestClient(app_mod.app)

    def test_get_config_renders_with_db_enabled(self, tmp_path, monkeypatch):
        with self._client(tmp_path, monkeypatch, with_db=True) as client:
            resp = client.get("/config")
        assert resp.status_code == 200
        # Sanity: form is rendered, expected sections are visible.
        assert "LLM &amp; Embedding" in resp.text or "LLM & Embedding" in resp.text
        assert "Retrieval &amp; Grouping" in resp.text or "Retrieval & Grouping" in resp.text
        assert "Save changes" in resp.text  # editable form

    def test_get_config_renders_with_db_disabled(self, tmp_path, monkeypatch):
        with self._client(tmp_path, monkeypatch, with_db=False) as client:
            resp = client.get("/config")
        assert resp.status_code == 200
        # When DB is disabled, the page is read-only and shows the notice.
        assert "Read-only mode" in resp.text
        # Save button should NOT render.
        assert "Save changes" not in resp.text


class TestConfigRouteSave:
    """Verify the save handler writes to the DB and clears the
    cached pipeline on app.state."""

    def test_save_dict_by_query_type_persists_full_dict(self, tmp_path, monkeypatch):
        """Per-type table editor: form fields named
        <module>__<key>__<query_type> get collected into a single
        dict and saved as one DB row."""
        from fastapi.testclient import TestClient
        db_path = tmp_path / "cfg.db"
        monkeypatch.setenv("NORA_CONFIG_DB", str(db_path))
        monkeypatch.setenv("ENV_DIR", str(tmp_path))
        import importlib
        import core.src.web.app as app_mod
        importlib.reload(app_mod)
        with TestClient(app_mod.app) as client:
            data = {
                "_submitted_by": "test",
                # All required scalars (validation expects each schema field)
                "llm__llm_provider": "ollama",
                "llm__llm_model": "test-model",
                "llm__llm_base_url": "",
                "llm__llm_api_key": "",
                "llm__llm_timeout": "0",
                "llm__embedding_provider": "ollama",
                "llm__embedding_model": "test-emb",
                "retrieval__gap_threshold": "0.05",
                "pipeline__max_distance_threshold": "0.5",
                "pipeline__top_k_cap": "0",
                # The new per-type rows: only some types have values
                "retrieval__bm25_weight_by_type__fact": "0.9",
                "retrieval__bm25_weight_by_type__summarize": "0.1",
                "retrieval__bm25_weight_by_type__single_doc": "",  # empty → skipped
            }
            resp = client.post("/api/config/save", data=data)
        assert resp.status_code == 200
        assert "Saved" in resp.text
        cs = ConfigStore(db_path)
        saved = cs.get("retrieval", "bm25_weight_by_type")
        assert saved is not None
        assert saved.get("fact") == 0.9
        assert saved.get("summarize") == 0.1
        # Empty cell wasn't saved → key absent
        assert "single_doc" not in saved


    def test_save_persists_value(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        db_path = tmp_path / "cfg.db"
        monkeypatch.setenv("NORA_CONFIG_DB", str(db_path))
        monkeypatch.setenv("ENV_DIR", str(tmp_path))
        import importlib
        import core.src.web.app as app_mod
        importlib.reload(app_mod)
        with TestClient(app_mod.app) as client:
            # Populate values so the save coerces correctly. Bool fields
            # without a form value coerce to False.
            data = {
                "_submitted_by": "test",
                "llm__llm_provider": "ollama",
                "llm__llm_model": "test-model",
                "llm__llm_base_url": "",
                "llm__llm_api_key": "",
                "llm__llm_timeout": "0",
                "llm__embedding_provider": "ollama",
                "llm__embedding_model": "qwen3-embedding:4b-q8_0",
                # Skip bool fields → will be saved as False
                "retrieval__gap_threshold": "0.05",
                "pipeline__max_distance_threshold": "0.5",
                "pipeline__top_k": "10",
            }
            resp = client.post("/api/config/save", data=data)
        assert resp.status_code == 200
        assert "Saved" in resp.text
        # Verify a known value made it to the DB.
        cs = ConfigStore(db_path)
        assert cs.get("llm", "llm_model") == "test-model"
