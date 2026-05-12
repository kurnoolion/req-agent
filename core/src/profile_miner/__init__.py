"""Mine document-profile regex patterns from human corrections.

The Review tab on the web UI writes per-doc corrections to
``<env_dir>/corrections/<doc_id>_corrections.json``. This module reads
those files, joins each correction to its source block in the IR, asks
an LLM to generalise the correction into a regex, and emits a proposed
profile patch at ``<env_dir>/reports/profile_patch_<doc_id>.json``.

Public surface:
- ``EnrichedCorrection`` — a single correction joined to its IR block
  (plus ±N neighbours) ready for redaction and prompting.
- ``ProfileFieldPatch`` / ``ProfilePatch`` — the structured output the
  CLI emits per document; a human reviews these before merging into
  ``customizations/profiles/<MNO>_<plan>.json``.
- ``Redactor`` — `<MNO0>`, `<PLAN0>`, `<MNO0>_REQ_<PLAN0>_\\d+`
  placeholders. Bidirectional (redact + restore) so LLM-emitted regex
  re-acquires canonical placeholders before going into the patch file.
- ``load_corrections(env_dir, doc_id=None) -> list[EnrichedCorrection]``
- ``mine_patterns(corrections, llm) -> ProfilePatch`` — cluster by
  ``expected_reason``, prompt the LLM once per cluster, return the
  patch.
- ``profile_miner_cli.main`` — entrypoint
  (``python -m core.src.profile_miner.profile_miner_cli``).
"""

from core.src.profile_miner.apply_patch import (
    ApplyReport,
    FieldChange,
    apply_patch,
    apply_patch_files,
    merge_regex,
)
from core.src.profile_miner.records import (
    EnrichedCorrection,
    ProfileFieldPatch,
    ProfilePatch,
)
from core.src.profile_miner.redaction import Redactor
from core.src.profile_miner.loader import load_corrections
from core.src.profile_miner.miner import mine_patterns

__all__ = [
    "ApplyReport",
    "EnrichedCorrection",
    "FieldChange",
    "ProfileFieldPatch",
    "ProfilePatch",
    "Redactor",
    "apply_patch",
    "apply_patch_files",
    "load_corrections",
    "merge_regex",
    "mine_patterns",
]
