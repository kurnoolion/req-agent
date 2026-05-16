## 2026-05-16 — strand opened; design converged on standalone sandbox

### Done this session
- Read the SIRA paper abstract + repo (arXiv 2605.06647; github.com/facebookresearch/sira; week-old, Anshumali Shrivastava et al.). Core technical claim is corpus-discriminative term selection via DF-filtered LLM enrichment — *not* just LLM synonym injection. Dual-sided (corpus + query) by design.
- Iterated on the integration shape over two pushbacks:
  - I proposed primitives-first decomposition (query-expansion alone as Phase 1). You correctly rejected: SIRA's contribution is the dual-sided enrichment paired with the DF-filter; one side alone is just noise.
  - I proposed dual-sided enrichment as a NORA-internal chunk-builder change. You correctly rejected: hybrid system tests something neither team designed; standalone is cleaner attribution + cheaper engineering + reversible.
- Converged on: **run SIRA's full published pipeline as a standalone sandbox**, with two thin adapters (NORA parse output → BEIR-shape `corpus.jsonl` + 18-Q eval → `queries.jsonl`/`qrels.tsv`; SIRA output → NORA req_id-level recall/MRR). Phase 2 (integration shape) only fires if Phase 1 shows lift.
- Locked five Phase-1 decisions into STRAND.md Notes:
  1. LLM = proprietary 100B+ via 50-line FastAPI `/v1/chat/completions` shim wrapping `customizations/llm/proprietary_provider.py` (SIRA source unmodified). Swap to local Qwen-35B + sglang post-DGX-Spark (~1 week).
  2. Acronym pre-expansion in `ACRONYM (Full Expansion)` bracket form — matches NORA's chunk-builder convention, apples-to-apples vs NORA BM25 lane.
  3. Heading-only reqs included with title-only text — spec heading often *is* the requirement.
  4. Struck reqs already absent from `tree.requirements` (parser drops per D-031/D-037); no extra adapter filter.
  5. Combined corpus across plans (18-Q eval spans plans).
- Bound session to strand.

### Out-of-scope work in same session
- Parse page UI merger (Summary + Review unified; Bootstrap tab deleted; 3 cols added to DocSummary). Commits acd6be8 + 2a2aeb5.
- `parse_debug references` diagnostic + `references-handling` strand opening. Commit 2500b2a.
- These touched parser / web / extraction modules; no overlap with sira.

### In progress
- Phase 0 not started — strand exists in design-only state.

### Next
- **Phase 0**: clone github.com/facebookresearch/sira to a `sandbox/` sibling dir (not under `core/src/`). Install (Python 3.12 + Rust). Run their `scifact` example end-to-end against the proprietary LLM via a stub shim. Read the actual prompt files (`doc_v06.txt` / `query_v06.txt` / `relevance_v02.txt` or whichever task-family variants ship — couldn't fetch them via WebFetch, need a clone).
- Decision after Phase 0: is the prompt shape transferable to telecom-requirements without rewriting? If `doc_claim` / `query_claim` look usable as-is, proceed to Phase 1 adapter; otherwise spike a `doc_requirement` / `query_requirement` variant.

### Flags
- SIRA's LLM call shape (sglang-native schema-constrained gen vs OpenAI-style chat-completions) is unknown until we read `src/sira/llm.py` post-clone. The shim's translation layer complexity depends on it — flagged as Phase 0 finding, not a blocker.
