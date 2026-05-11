"""Pytest configuration for core/tests.

Stubs out the `weaviate` / `weaviate.classes` modules so that
schema tests (TestRequirementSchema, etc.) can run on machines
where the weaviate-client package is not installed.

The stubs produce lightweight SimpleNamespace objects whose
.name / .index_searchable / .index_filterable / .target_collection
attributes are the same ones the real Property / ReferenceProperty
objects carry, which is all the schema tests inspect.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock


def _make_property(
    name: str,
    data_type=None,
    *,
    skip_vectorization: bool = True,
    index_searchable: bool = False,
    index_filterable: bool = True,
):
    return SimpleNamespace(
        name=name,
        data_type=data_type,
        skip_vectorization=skip_vectorization,
        index_searchable=index_searchable,
        index_filterable=index_filterable,
    )


def _make_reference(name: str, target_collection: str):
    return SimpleNamespace(name=name, target_collection=target_collection)


# ── Build a minimal weaviate.classes namespace ─────────────────────────────

_DataType = SimpleNamespace(
    TEXT="text",
    TEXT_ARRAY="text[]",
    BOOL="bool",
    DATE="date",
    INT="int",
    NUMBER="number",
    UUID="uuid",
)

_Configure = SimpleNamespace(
    Vectorizer=SimpleNamespace(none=staticmethod(lambda: None))
)

_config_ns = SimpleNamespace(
    Property=_make_property,
    ReferenceProperty=_make_reference,
    Configure=_Configure,
    DataType=_DataType,
)

_wvc_stub = SimpleNamespace(config=_config_ns)

# ── Inject stubs only when the real package is absent ─────────────────────

if "weaviate" not in sys.modules:
    _weaviate_stub = MagicMock()
    _weaviate_stub.classes = _wvc_stub
    sys.modules["weaviate"] = _weaviate_stub
    sys.modules["weaviate.classes"] = _wvc_stub
    # Sub-modules that may be imported elsewhere
    sys.modules["weaviate.classes.config"] = _config_ns  # type: ignore[assignment]
    sys.modules["weaviate.connect"] = MagicMock()
    sys.modules["weaviate.auth"] = MagicMock()
