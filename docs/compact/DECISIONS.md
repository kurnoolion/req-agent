# Decisions

*D-001..D-012 reconstructed 2026-04-21 from `design-inputs/SESSION_SUMMARY.md` and TDD; rationale partial.*

<!--
Template (keep entries tight — this file is always in context):

## D-XXX: Short title
**Status**: Active · **Date**: YYYY-MM-DD
**Decision**: What was chosen.
**Why**: Reason; rejected alternatives inline (vs X: ...).
**Consequences**: What this forces or rules out.
-->

---

## D-001: KG + RAG hybrid over pure vector RAG
**Status**: Active · **Date**: 2026-04-21
**Decision**: Knowledge Graph routes queries (WHERE), targeted vector RAG ranks within scope (WHAT), requirement hierarchy provides structural CONTEXT.
**Why**: Pure vector RAG failed on MNO Q&A — no relationships, undirected scope, lost hierarchy, weak telecom terminology. Graph traversal captures cross-doc/MNO/release links pure RAG can't follow. Vs pure-graph: loses semantic ranking.
**Consequences**: `src/graph/` owns routing, `src/vectorstore/` ranking, `src/query/` orchestrates. Unscoped vector search is a hard-flag.

---

## D-002: Single unified graph + vector store, not MxN partitioned
**Status**: Active · **Date**: 2026-04-21
**Decision**: One graph + one vector store across all MNOs/releases. Logical partitioning via `mno`/`release`/`doc_type` metadata. Standards and Feature nodes shared.
**Why**: Cross-MNO comparison and cross-release diffs become natural traversals; partitioned stores make them merge-with-correctness-risk operations.
**Consequences**: Every node/chunk carries MNO/release/doc_type. Filters enforced at every retrieval path.

---

## D-003: Profile-driven generic structural parser, no per-MNO code
**Status**: Active · **Date**: 2026-04-21
**Decision**: LLM-free `DocumentProfiler` derives a JSON profile (headings, req-ID pattern, zones, cross-refs); `GenericStructuralParser` applies it to emit a `RequirementTree`. New MNO = new profile, no code.
**Why**: Eliminates per-MNO parser drift; keeps LLM out of structural path (determinism, speed); profile is human-reviewable. Vs per-MNO parsers: maintenance grows linearly. Vs LLM parsing: cost/latency/non-determinism.
**Consequences**: Profile quality is critical — wrong profile poisons all that MNO's docs. Validation against held-out docs required. Profiler and parser stay decoupled.

---

## D-004: Option C Hybrid Selective for standards ingestion
**Status**: Active · **Date**: 2026-04-21
**Decision**: Ingest cited 3GPP/GSMA/OMA sections plus parent section, adjacent subsections, and definitions. Aggregate references by `(spec, release)`; download once.
**Why**: Full specs prohibitive in size; section-only loses interpretability; Option C bounds cost while preserving context.
**Consequences**: `src/standards/` resolves spec+release → URL, parses 3GPP DOCX trees. Release-aware: separate `Standard_Section` nodes per release.

---

## D-005: Bottom-up LLM-derived feature taxonomy with mandatory human review
**Status**: Active · **Date**: 2026-04-21
**Decision**: LLM extracts candidate features per doc, consolidator merges them, human review required before graph consumption. Human edits land in `<doc_root>/corrections/taxonomy.json`.
**Why**: Pre-defined taxonomies drift from corpus; bottom-up stays aligned. LLM for extraction only; review prevents hallucinated features.
**Consequences**: Pipeline has a human checkpoint. Corrections workflow (D-011) is hard dep. Unreviewed runs degrade answers.

---

## D-006: `LLMProvider` Protocol (structural typing)
**Status**: Active · **Date**: 2026-04-21
**Decision**: Protocol in `src/llm/base.py` with `complete(prompt, system, temperature, max_tokens) -> str`. Any class with matching `complete()` satisfies it; swap by instance.
**Why**: Multi-LLM support (Claude design-time, Ollama PoC, on-prem proprietary) without caller changes. Vs ABC: no inheritance lock-in.
**Consequences**: No LLM SDK imports outside `src/llm/`. All callers import the Protocol. Protocol signature change is hard-flag.

---

## D-007: `EmbeddingProvider` and `VectorStoreProvider` Protocols
**Status**: Active · **Date**: 2026-04-21
**Decision**: Same pattern as D-006 for embeddings and vector stores. `VectorStoreConfig` (JSON) selects provider/model/metric/chunking. Initial impls: `SentenceTransformerEmbedder`, `ChromaDBStore`.
**Why**: A/B evaluation across embedding models/backends without caller changes; uniformity with D-006.
**Consequences**: `chromadb` and `sentence-transformers` imported only inside vectorstore module. Experimentation is config-driven. Protocol change is hard-flag.

---

## D-008: Web UI = FastAPI + Bootstrap 5 + HTMX
**Status**: Active · **Date**: 2026-04-21
**Decision**: FastAPI + Bootstrap 5 + HTMX + jinja2. Zero npm/JS build. Vendored static assets. Background jobs via `asyncio.create_task()`. SSE log streaming. SQLite job queue via `aiosqlite`. Reverse-proxy compatible via `root_path`.
**Why**: Vs Streamlit (single-user); vs Gradio (ML-demo abstractions); vs Airflow (heavyweight). FastAPI+HTMX = multi-user, async, partial updates, no JS build, Python-native.
**Consequences**: `src/web/` is first-class. CDN fetches are hard-flag. Multi-user auth deferred (production concern).

---

## D-009: Metrics — 5-category SQLite, fire-and-forget middleware
**Status**: Active · **Date**: 2026-04-21
**Decision**: Categories: REQ (endpoint timing), LLM (`OllamaProvider.last_call_stats`), PIP (stage timing), RES (CPU/RAM/GPU via `/proc` + `nvidia-smi`), MET (custom). Persistent SQLite at `web/nora_metrics.db`. `MetricsMiddleware` never blocks responses. `compact_report()` emits MET lines with no proprietary content.
**Why**: Production runs hardware AI partner can't see; observability via compact reports. Vs Prometheus/Grafana: too operational. Vs psutil: dep not always available.
**Consequences**: Every stage emits PIP; every LLM call emits LLM; long stages emit RES. Schema is internal contract. No proprietary content in metric values.

---

## D-010: Multi-format extraction via normalized `DocumentIR`
**Status**: Active · **Date**: 2026-04-21
**Decision**: Per-format extractors emit a common `DocumentIR` (ContentBlock, FontInfo, Position, BlockType). DOC → DOCX via headless LibreOffice. Downstream consumes only `DocumentIR`.
**Why**: One IR isolates format concerns to extraction boundary; downstream contracts stay stable. pymupdf for text+fonts, pdfplumber for tables.
**Consequences**: New format = new extractor only. `DocumentIR` schema is internal contract. Font metadata must be preserved (profiler clusters on font size).

---

## D-011: Corrections override pattern
**Status**: Active · **Date**: 2026-04-21
**Decision**: Auto-generated artifacts → `<doc_root>/output/`. Human overrides → `<doc_root>/corrections/` (same filenames). Pipeline copies `corrections/*.json` over outputs on every run.
**Why**: File-based convention; no DB, no merge logic. Human authority is explicit. Pairs with `/switch-phase` review.
**Consequences**: Every artifact with human-review need uses this. `src/corrections/` owns diff/compactor/FixReport. Web UI writes directly to `corrections/`.

---

## D-012: Chat-mediated collaboration — stable error codes + compact reports
**Status**: Active · **Date**: 2026-04-21
**Decision**: (a) Every pipeline failure emits a stable prefixed code (`EXT-`, `PRF-`, `PRS-`, `RES-`, `TAX-`, `STD-`, `GRA-`, `VEC-`, `EVL-`, …) registered in `src/pipeline/error_codes.py`; logs persist locally. (b) Every cross-boundary artifact has a paired compact format — RPT (pipeline), MET (metrics), FIX (corrections), QC (quality). One record per line, no internal content. (c) QC templates are fixed-field (numbers + Y/N).
**Why**: AI partner can't see proprietary artifacts; compact + stable codes turn that into a tractable surface. No-proprietary-content is a hard invariant.
**Consequences**: Every new artifact ships error-code prefix + compact schema + QC template. `drift-check`/`close-session` hard-flag artifacts missing these. Authority for remote-collaboration NFRs.

---

## D-013: v1 PoC corpus = single-MNO (Verizon Feb 2026); multi-MNO is post-v1
**Status**: Active · **Date**: 2026-04-27
**Decision**: v1 ships against VZW Feb 2026 only. Cross-MNO and release-diff success criteria are post-v1. Schemas (D-002) stay multi-MNO-ready: every node/chunk carries `mno`/`release`.
**Why**: NFR-15 (≥90% weighted overall) must be reachable before adding corpus complexity. Multi-MNO needs proprietary-LLM integration that's also out of v1. Validate KG+RAG architecture on a known dataset first.
**Consequences**: PROJECT.md In/Out scope marks multi-MNO post-v1. NFR-15 measured on VZW only. Cross-MNO/release-diff are *capabilities* but not *v1-verified outcomes*. Adding 2nd MNO triggers KG memory ceiling re-eval.

---

## D-014: Test_Case node/edge types kept in schema, populated post-v1
**Status**: Active · **Date**: 2026-04-27
**Decision**: Schema retains Test_Case nodes/edges. v1 populates zero. FR-7 documents this; FR-26 (Deferred) parks the parser.
**Why**: Schema stability avoids future migration on persisted graph state. Test_Case is known-future, not hypothetical.
**Consequences**: Graph builder paths compile but emit empty. `drift-check` shouldn't flag the slot as unused.

---

## D-015: NFR-15 acceptance = weighted-overall ≥ 90%, not raw req-ID accuracy
**Status**: Active · **Date**: 2026-04-27
**Decision**: NFR-15 binds acceptance to weighted-overall ≥ 90% on user-curated A/B eval set. Five metrics: completeness/accuracy/citation/standards/hallucination-free at 0.30/0.25/0.20/0.15/0.10. Raw req-ID recall is the 25% accuracy slice, not standalone.
**Why**: Weighted is harder to game — high req-ID recall can coexist with poor citations and standards integration.
**Consequences**: Eval reports must show per-metric + weighted overall. Changing weights = hard-flag DECISIONS event. NFR-16 binds dataset to user-curated only — synthetic Q&A doesn't count.

---

## D-016: Production runs behind authenticating reverse proxy; no in-app auth
**Status**: Active · **Date**: 2026-04-27
**Decision**: Auth is a deployment responsibility. System never sees raw login traffic. `root_path` (D-008) accommodates reverse-proxy.
**Why**: In-app auth couples to an IdP, contradicts on-prem-only (NFR-1), bloats v1. Corp envs already run authenticated proxies.
**Consequences**: No password storage, sessions, or IdP integration. `root_path` honored end-to-end (FR-19). Direct FastAPI exposure = deployment misconfig, not v1 bug.

---

## D-017: Domain-expert correction validation = architect FIX-report review (workflow rule)
**Status**: Active · **Date**: 2026-04-27
**Decision**: Architect reviews compact FIX report before each correction-driven re-run. Workflow rule, not code-enforced gate. Pipeline does not block on approval.
**Why**: Code-gated approval needs RBAC/workflow engine — incompatible with v1's no-RBAC stance. FIX reports already strip proprietary content (D-012). Idempotent pipeline (NFR-13) enables revert by editing corrections file.
**Consequences**: Trusted-team assumption explicit. Sloppy review is the v1 failure mode. No rollback infrastructure needed. Contributors table owns this validation channel.

---

## D-018: DOC and XLS parked as Deferred FR-27; TDD design intent preserved
**Status**: Active · **Date**: 2026-04-27
**Decision**: TDD §5.1 multi-format design (PDF/DOC/DOCX/XLS/XLSX) preserved. v1 implements PDF+DOCX+XLSX. DOC and XLS land in Deferred FR-27, revisit "when corpus needs them".
**Why**: Trimming TDD erases known-future capability the abstraction (D-010) was built for. Adding extractor is single integration path.
**Consequences**: drift-check won't flag DOC/XLS as missing. New extractor = new module, no design rev.

---

## D-019: Three-tier code organization — `core/` + `customizations/` + `config/`
**Status**: Active · **Date**: 2026-04-27
**Decision**: `core/` = AI-generated source (`core/src/`, `core/tests/`). `customizations/` = AI-scaffolded code humans complete or own. `config/` = per-module settings.
**Why**: Makes AI/human collaboration boundary explicit in filesystem; lets `drift-check`/`regen-map` apply per-zone rules.
**Consequences**: All MODULE.md paths change. CLI: `python -m core.src.<module>.<module>_cli`. Triggers a reorg session.

---

## D-020: Bi-directional `core ↔ customizations` deps; no AI/human authorship marking in git
**Status**: Active · **Date**: 2026-04-27
**Decision**: `core/` and `customizations/` may import each other freely. Commits don't mark authorship — directory implies it. Manual core edits exceptional, not forbidden.
**Why**: Real dep flow is bidirectional (core's `LLMProvider` consumed by customizations; customizations' profiles consumed by core's parser). Boundary is structural, not authorial.
**Consequences**: drift-check accepts cross-boundary cycles. `regen-map` recognizes both directions. No CI rule for "AI-only commits to core" — review governs.

---

## D-021: One config file per module under `config/`; runtime DBs and per-env data are not config
**Status**: Active · **Date**: 2026-04-27
**Decision**: `config/<module>.json` per module. Runtime SQLite DBs → `<env_dir>/state/`. Per-env user data (corrections, eval Q&A) → env, not `config/`.
**Why**: Centralized + per-module avoids change-magnet single file. Excluding state/per-env keeps `config/` to deploy/install settings, committable to git.
**Consequences**: Modules read only their own config file. New module config = new file under `config/`. `web/config.json` migrated to `config/web.json`.

---

## D-022: Per-env runtime directory `<env_dir>` as single root for all runtime data
**Status**: Active · **Date**: 2026-04-27
**Decision**: `<env_dir>` partitions: `input/<MNO>/<release>/`, `out/{extracted,parsed,resolved,taxonomy,standards,graph,vectorstore}/`, `state/{nora.db, nora_metrics.db}`, `corrections/`, `reports/`, `eval/`. Resolved via `environments/<name>.json` or `--env-dir`.
**Why**: Self-contained pipeline invocations; `rm -rf <env_dir>` is safe; env state can be zipped/shipped. Repo stays artifact-free.
**Consequences**: All file-writing modules take `env_dir` as parameter. `data/` deprecated. Repo-root PDFs move to `<env_dir>/input/VZW/Feb2026/`. Web UI runtime DBs move to `<env_dir>/state/`.

---

## D-023: Source documents under `<env_dir>/input/<MNO>/<release>/`
**Status**: Active · **Date**: 2026-04-27
**Decision**: Path-encoded MNO (upper-case: VZW/ATT/TMO) and release tag (e.g., `Feb2026`). Pipeline reads from path, not filename.
**Why**: Path-encoded metadata survives renames; aligns with multi-MNO post-v1 (new MNO = new directory).
**Consequences**: `infer_metadata_from_path` is authoritative; filename fallbacks deprecated.

---

## D-024: Initial `customizations/` = `profiles/` + proprietary-LLM provider boilerplate
**Status**: Active · **Date**: 2026-04-27
**Decision**: `customizations/profiles/<profile>.json` (was repo-root `profiles/`); `customizations/llm/<provider>.py` (proprietary-LLM scaffold). Co-located tests. New human-touch surfaces move here with their own DECISIONS entry.
**Why**: Profiles are human-curated against real docs; proprietary-LLM provider is sensitive and per-deployment. Two anchors give the convention shape.
**Consequences**: `profile_cli` loads from `customizations/profiles/`. LLM registration looks at both `core/src/llm/` and `customizations/llm/`. Corrections data stays under `<env_dir>/corrections/` (D-022).

---

## D-025: HuggingFace as default 3GPP source; DOCX over MD; FTP retained as fallback
**Status**: Active · **Date**: 2026-04-28
**Decision**: Pluggable `SpecDownloader.source` (`"huggingface"` | `"3gpp"`); HF default. Use HF `original/Rel-{N}/{NN}_series/` DOCX side. Precedence: CLI `--standards-source` > `NORA_STANDARDS_SOURCE` env > `EnvironmentConfig.standards_source` > `"huggingface"`. New `core/src/standards/hf_source.py` uses stdlib `urllib` only.
**Why**: HF DOCX 2.3× faster than FTP (594s vs 1384s for 54 specs), single-domain (proxy-friendly), no LibreOffice DOC→DOCX needed. DOCX over MD: parser already targets DOCX; MD has Rel-20 gaps and loses font/style. Default-flip helps work-laptop case most.
**Consequences**: Both sources land same `data/standards/TS_{spec}/Rel-{N}/` cache; downstream source-agnostic. LibreOffice optional unless source=3gpp. Adds dep on `huggingface.co` for default path; outages → manual `--standards-source 3gpp`.

---

## D-026: OpenAI-compatible LLM provider for cloud APIs
**Status**: Active · **Date**: 2026-04-28
**Decision**: `OpenAICompatibleProvider` in `core/src/llm/openai_provider.py` satisfies `LLMProvider` Protocol. One class for any OpenAI Chat Completions endpoint (OpenRouter, Together, DeepInfra, Groq, vLLM/SGLang, OpenAI itself) via `base_url`/`api_key`/`model` (constructor or `NORA_LLM_*` env vars). Stdlib `urllib` only. Selected via `--llm-provider` / `NORA_LLM_PROVIDER` / `EnvironmentConfig.model_provider`. Protocol surface unchanged.
**Why**: OpenAI Chat Completions is de-facto cloud standard — one class covers ~all providers. Stdlib matches `OllamaProvider`. Cloud needed now to test model-vs-structural accuracy gap independent of DGX Spark availability.
**Consequences**: Cloud path **only for non-proprietary corpora** (OA on dev PC); work-laptop/VoWiFi stays on Ollama. Cost ~$0.30-1 per full run. Silent fallback to MockLLMProvider when env vars missing burned us once — `require_real=True` hardening on Next list. DGX swap when shipped = two-env-var change.

---

## D-027: Parser anchors Requirements from table cells; paragraph wins on duplicate
**Status**: Active (eval regression observed; mitigation pending — see STATUS Flags) · **Date**: 2026-04-28
**Decision**: Add table-cell req-ID pass in `GenericStructuralParser._build_sections`. Per `BlockType.TABLE` row: scan column 1 first, fallback to all cells; one anchor per row. Paragraph wins on duplicate `req_id`. Table-anchored Requirements have `section_number=""` and inherit `parent_section`/`parent_req_id`/`zone_type` from the surrounding paragraph-anchored section; reuses profile's `requirement_id.pattern`.
**Why**: ~46% of internal refs were `broken` because target IDs live only in table cells and never became Requirements. Column-1-first matches the dominant OA layout; all-cells fallback handles row-label tables. Paragraph-wins preserves richer body content.
**Consequences**: MODULE.md invariant relaxed to "Requirement is anchored (paragraph OR table)" — `section_number=""` is valid. Test renamed `test_every_requirement_is_anchored`. Schema unchanged → downstream stages absorb new Requirements without code change. Eval regression on the OA 18-Q set diagnosed as retrieval pollution from thin table chunks; metrics + mitigation paths in STATUS.

---

## D-028: Qwen3-235B-A22B + OpenRouter as best-case baseline; same model targets DGX Spark
**Status**: Active · **Date**: 2026-04-28
**Decision**: Qwen3-235B-A22B via OpenRouter now; via Ollama on DGX Spark when shipped. Same `OpenAICompatibleProvider` (D-026); swap = two env vars, no re-baseline at hardware change. Cloud cleared **only for OA corpus** (public); proprietary corpora stay on local Ollama.
**Why**: MoE (~22B active) suits Spark's memory-rich/bandwidth-modest profile (~273 GB/s LPDDR5X) better than dense 70B. Hybrid thinking + strong IFEval target the instruction-following gap (`gemma4:e4b` summarized instead of emitting JSON). 128K native context. OpenRouter: one API/key for ~100 models; ~10% markup buys optionality at sub-$1 per run.
**Consequences**: Two corpora / two LLM setups codified: OA → OpenRouter cloud; VoWiFi → local Ollama smaller model. Cloud path never carries proprietary content. DGX arrival → hardware-only re-baseline. Baseline numbers in STATUS Done entries.

---

## D-029: LLM and embedding provider/model selectable at runtime; remote LLM + local embeddings in v1
**Status**: Active · **Date**: 2026-04-29
**Decision**: Symmetric precedence for both: **CLI flag > `NORA_*` env > `EnvironmentConfig` > built-in default**. LLM: `ollama` or `openai-compatible`. Embedding: `sentence-transformers` or `ollama` (new `OllamaEmbedder` alongside existing `SentenceTransformerEmbedder`). Pipeline talks only to `make_embedder(config)`; new backend = new file. `EnvironmentConfig` carries `model_provider`/`model_name`/`embedding_provider`/`embedding_model`.
**Why**: Different deployments have different access (cloud vs air-gapped). Embedding was hard-coded in `VectorStoreConfig()`. Vs config-only: loses ergonomic CLI overrides. Cloud embedding deferred — OpenRouter doesn't host embeddings, separate API seam adds creds/billing surface for marginal v1 benefit.
**Consequences**: `environments/<name>.json` is canonical record of deployed models. `NORA_EMBEDDING_PROVIDER`/`NORA_EMBEDDING_MODEL` are public env contracts. Cloud-embedding remains deferred, not non-goal. Preserves D-006/D-007 (Protocol + injection).
**Related**: D-006, D-007, D-026.

## D-030: Form-factor applicability — per-Requirement attribute with parser-side hierarchical inheritance

**Date**: 2026-05-01
**Status**: Accepted
**Phase**: Architecture

**Context**
FR-32 introduces form-factor applicability (e.g. `["smartphone", "tablet"]`)
as a per-`Requirement` attribute with hierarchical inheritance: explicit
value on the requirement wins; otherwise inherit from parent up the chain;
otherwise fall back to a document-level applicability section if present.

**Decision**

- **Schema**: `Requirement.applicability: list[str]` (parser/structural_parser.py),
  free-form labels per FR-32. Empty list = unknown; downstream stages don't
  filter on empty.
- **Profile** (profiler/profile_schema.py): new `ApplicabilityDetection`
  dataclass on `DocumentProfile` with two fields —
  - `requirement_patterns: list[str]`: regex patterns; first-match wins;
    group 1 contains the comma/pipe-separated form-factor text.
  - `global_section_pattern: str`: regex for the heading text of a
    document-level applicability section; that section's contents seed
    the root default.
  Regex-only by direction; no keyword bag-of-words fallback.
- **Parser pass**: new `_apply_applicability(sections, profile)` post-pass
  after `_link_parents`. Walk sections in document order; resolve global
  root default once; per section try patterns against the section's own
  text, else inherit from parent's already-resolved applicability, else
  fall back to root default.
- **Table-anchored Requirements** inherit through the existing
  `_propagate_hierarchy_to_table_reqs` pass (extended to copy
  `applicability` alongside `hierarchy_path` / `zone_type`).
- **Downstream**: graph + chunk_builder gain one-line `r.get("applicability", [])`
  propagation, mirroring the existing `zone_type` pattern. Metadata-only in v1;
  no retrieval-time `where` filter.

**Why this over alternatives**
- *Side-channel manifest*: rejected. Applicability is intrinsic to each
  requirement; splitting it complicates corrections, graph hydration, audit.
- *Inline detection in `_build_sections`*: rejected. Parent's applicability
  isn't resolved at section-creation time. Post-pass mirrors how
  `zone_type` already flows.
- *Keyword bag-of-words fallback*: dropped per user direction. Trade-off:
  varied phrasings need one regex each; corrections workflow makes that a
  JSON edit, not a code change.
- *Controlled vocabulary*: deferred per FR-32 (free-form labels in v1;
  revisit at second carrier).

**Consequences**
- Additive schema change to `Requirement` and `DocumentProfile` — soft flag
  in parser/MODULE.md and profiler/MODULE.md.
- Profiler does **not** auto-derive these patterns in v1. Humans curate
  `requirement_patterns` per corpus via corrections (D-011, FR-15);
  auto-detection becomes possible once a second corpus reveals patterns
  worth generalizing.
- Future query-side filtering (`where={"applicability": "smartphone"}`)
  is a one-line addition — left as a Deferred capability.

**Related**: FR-32, FR-15, D-007, D-011, parser MODULE.md `zone_type`
propagation pattern.

## D-031: Strikeout-content omission — `FontInfo.strikethrough` IR field, format coverage, parser drop semantics

**Date**: 2026-05-01
**Status**: Accepted (extended by [D-060](#d-060-unified-strike-model--partial-text-strike-via-runs-mark-dont-drop-at-extract-time))
**Phase**: Architecture
**Note (2026-05-09)**: D-060 extends this ADR. Geometric strike-line detection (`_table_is_struck`, `_detect_struck_rows`, `_span_struck`) and the `FontInfo.strikethrough` field stay. What changed: PDF/XLSX extractors no longer **drop** struck rows from the IR — they mark via `row_runs`, parser drops at parse time. DOCX gains partial-text strike via runs; the "any-run-struck" rule for paragraph-level `font_info.strikethrough` becomes "every-run-struck" (partial strike now keeps the block and uses runs to drop spans). See D-060 for the full unified-model rationale.

**Context**
FR-33 requires the system to detect strikethrough formatting and drop the
affected content (struck-through requirements are document-author deletions
that must not surface to the user or downstream stages). FR-33 covers all
three supported formats: PDF, DOCX, XLSX.

**Decision**

- **IR schema** (models/document.py): `FontInfo.strikethrough: bool = False`.
  Default False keeps existing IR JSONs readable without migration.
  Extractors that can't determine the signal leave it False (never None;
  binary signal keeps the consumer contract simple).
- **Per-format extractor surfacing**:
  - PDF: PyMuPDF `flags` bit 8 (`TEXT_FONT_STRIKEOUT`). Mixed-strike blocks
    use majority-of-characters; 50% defaults to False (no drop on ambiguity).
  - DOCX: `Run.font.strike` / `.dstrike`. Block-level signal is `any` —
    any run struck → whole paragraph struck.
  - XLSX: `Cell.font.strike`. Row drop only when **all** non-empty cells
    in the row are struck; partial strike is treated as in-cell editing.
    Sheet headings (synthesized from sheet titles) cannot be struck.
- **Drop point**: the **parser**, not the extractor. The IR is a faithful
  source representation; interpretation (including the
  `ignore_strikeout` toggle) lives in the parser. This keeps drops
  overrideable via corrections without re-extracting PDFs.
- **Override knob** (profile_schema.py): top-level
  `DocumentProfile.ignore_strikeout: bool = True`. Default ON makes
  FR-33 active out of the box; flip to False (via corrections workflow)
  for corpora that use strikethrough for annotation rather than deletion.
- **Parser behavior**: in `_build_sections`, when both
  `profile.ignore_strikeout` and `block.font_info.strikethrough` are
  True, skip the block (no heading classification, no body append, no
  table emission), increment a counter, log once per parse.
- **Compact-report visibility**: `RequirementTree` gains
  `parse_stats.struck_blocks_dropped: int`; the parse stage's compact
  RPT line gains a `struck=N` token alongside `req=N dep=N docs=N`.
  Per NFR-9.

**Why this over alternatives**
- *Drop at extractor*: rejected. Faithful IR enables corrections-workflow
  override without re-parsing PDFs and keeps IR auditable.
- *Per-span strike state in IR*: rejected. IR block granularity is
  paragraph-shaped; carrying span-level strike would require a much larger
  schema change than this FR justifies. Block-level majority/any/all
  per format is sufficient.
- *Always drop, no toggle*: rejected. Some carriers use strikethrough as
  emphasis. Default ON keeps FR-33 active; the toggle handles edge corpora.
- *Auto-detect "is this corpus strikethrough-as-deletion or
  strikethrough-as-emphasis?"*: deferred. Heuristic isn't reliable
  without labelled data; explicit toggle is more honest.

**Consequences**
- Soft-flag schema additions in models/MODULE.md, profiler/MODULE.md,
  parser/MODULE.md (additive, no breaking change).
- All three extractors gain strike-detection paths.
- Compact RPT format gains `struck=N` (NFR-9 honored).
- Existing IR JSONs and profile JSONs load safely with defaults that
  preserve correctness.

**Related**: FR-33, FR-15 (override path), NFR-9 (compact-format
counterpart), D-007 (profile is human-editable input).

## D-032: Definitions/acronyms expansion — per-document map on RequirementTree, chunk-build-time expansion

**Date**: 2026-05-01
**Status**: Accepted
**Phase**: Architecture

**Context**
FR-35 requires the profiler to detect each document's definitions /
acronyms / glossary section, extract `term → expansion` pairs, and have
the chunk builder expand the first occurrence of each term inline before
embedding. Per FR-35, expansion is per-document, not corpus-wide, to
preserve locality (e.g. `RAT` may mean different things in different MNO
documents).

**Decision**

- **Map location**: on `RequirementTree` (per-document parse output), not
  on the profile. New field `RequirementTree.definitions_map: dict[str, str]`,
  populated by the parser. Profile carries detection rules only; extracted
  values are corpus-content and belong with the parsed tree.
- **Expansion timing**: at chunk-build time, not query-time. Expanded text
  is what gets embedded — vectors carry the signal that retrieval scores
  against.
- **Detection** (profiler):
  - `DocumentProfile.heading_detection.definitions_section_pattern` (regex
    against heading text; default `(?i)acronym|definition|glossary`).
  - `DocumentProfile.definitions_entry_pattern` (regex with two capture
    groups; default supports common dash/colon separators: 16-char term
    cap to avoid prose-line false positives).
- **Extraction** (parser): new post-pass `_extract_definitions` after
  `_link_parents`. The definitions section is kept in the parsed tree.
- **Chunker behavior** (vectorstore/chunk_builder.py): `ChunkBuilder`
  accepts an optional `definitions_map`. First-occurrence-per-chunk
  expansion via `\b<term>\b`. Idempotent. Skips chunks belonging to the
  definitions section itself (avoid double-expansion).
- **Per-document scoping**: vectorstore builder threads each tree's
  `definitions_map` into the chunker per tree; never aggregated across
  trees. Enforced at chunk-build, not at store level (D-002 unified store
  preserved).
- **Corrections workflow**: per-document corrections at
  `<env_dir>/corrections/definitions/<plan_id>.json`. Pipeline merges
  correction values over extracted values for the same term.
- **Compact reports**: parse RPT gains `defs=N`; vectorstore RPT gains
  `expanded=N`. New error-code prefix `DEF-` (`DEF-E001`: definitions
  section detected but entry pattern matched zero entries). Honors NFR-9.

**Why this over alternatives**
- *Map on DocumentProfile*: rejected. Profile is per-corpus rules; map is
  per-document content. Mixing violates the existing profile↔tree seam.
- *Side-channel JSON outside the parsed tree*: rejected. New file, new
  producer, new corrections drop-path — too much surface for one field.
- *Query-time expansion*: rejected. Vectors computed from un-expanded
  text don't improve retrieval recall — defeats the purpose.
- *Corpus-wide map*: rejected per FR-35 (locality is the point).
- *Expansion every occurrence*: rejected. Over-anchors embeddings on the
  same expansion. First-per-chunk is enough signal.
- *Config knob to disable expansion*: rejected. Empty map = no-op; no
  switch needed. Corrections workflow handles edge cases.

**Consequences**
- Soft-flag schema additions in parser/MODULE.md
  (`RequirementTree.definitions_map`), profiler/MODULE.md (two pattern
  fields), vectorstore/MODULE.md (chunker constructor argument).
- New corrections drop-path under `<env_dir>/corrections/definitions/`
  with associated error-code prefix `DEF-` and compact-format counterpart
  per NFR-9.
- Embedding quality on acronym-shaped queries improves at the cost of
  slightly larger chunk text (bounded: one expansion per term per chunk).

**Related**: FR-35, FR-15, NFR-9, D-007, D-002.

## D-033: Heading classification — numbering required, style advisory

**Date**: 2026-05-01
**Status**: Accepted
**Phase**: Architecture (captured retroactively from the development-phase
commit that landed it; commit 9df8a19)

**Context**
Real-corpus review of profile.json against the VZW OA documents surfaced
two structural problems in the previous heading classifier:
- The numbering regex `^((?:\d+\.)+\d*)\s` required at least one dot, so
  top-level chapters in the form `"1 LTE Data Retry"` (no trailing dot)
  were silently rejected — entire subtrees missing from the parsed
  structure.
- `_classify_heading` required both a font/style match AND a numbering
  match; real-world specs apply styling inconsistently, so valid
  headings were dropped when fonts diverged. The profiler responded by
  emitting one detection rule per (font_size, bold, all_caps) cluster
  — three rules all at the same 13.5pt size in the OA corpus, none
  load-bearing.

**Decision**
Numbering pattern is the **necessary** signal for heading classification;
style/font in `profile.heading_detection.levels` is consulted as a hint
only and never gates.

- Relaxed numbering pattern: `^(\d+(?:\.\d+)*)\s+\S` — matches `"2"`,
  `"2.1"`, `"2.1.1.1"` uniformly. Section depth =
  `section_number.count(".") + 1`.
- Section-number extraction in the parser uses an internal canonical
  regex (`_SECTION_NUM_RE`), not the profile's, so older profiles with
  different capture-group shapes keep working.
- False-positive guards in `_classify_heading`: text length capped at 200
  chars; terminal-punctuation rejection (`. ! ?`) for blocks longer
  than 80 chars. Rejects numbered list items in body text
  (`"1. The system shall ..."`).
- **Section-number deduplication** in `_build_sections`: the first
  heading with a given section number wins; subsequent matches are
  demoted to body text appended to the current section.
- Profiler: when numbering depth >= 2, emit `method="numbering"` and a
  single advisory level rule capturing the dominant heading style
  (kept for human curation, ignored by the parser). When numbering is
  absent or shallow, fall back to legacy `method="font_size_clustering"`.
- Default `HeadingDetection.method` changed from `"font_size_clustering"`
  to `"numbering"`.

**Why this over alternatives**
- *Style-as-gate (previous behavior)*: rejected. Real specs apply
  styling inconsistently; fonts get lost in extraction; valid headings
  drop. The bug we fixed.
- *Hybrid (require style OR numbering)*: rejected. Without firm length /
  punctuation guards, numbered list items in body flip to headings.
- *Stricter regex (require trailing dot)*: rejected per OA evidence —
  top-level chapters use `"N Title"` form without a dot. A stricter
  regex misses an entire hierarchy level.
- *Per-line section-number-from-profile capture-group shape*: rejected.
  Profile patterns vary in capture-group structure (legacy
  `^((?:\d+\.)+\d*)\s` vs new `^(\d+(?:\.\d+)*)\s+\S`); decoupling the
  gate from the section-number extractor avoids breaking older profiles.

**Consequences**
- Public-surface contract shift on parser's `_classify_heading` — gate
  semantics changed. Soft flag in parser/MODULE.md (additive Invariant
  noting numbering-as-gate).
- Section-number uniqueness is now a hard invariant — first heading wins.
- Profile schema: `HeadingDetection.method` default changed; old JSONs
  with `"font_size_clustering"` keep loading and working (parser still
  gates on numbering; the old levels become inert advisory).
- Surfaced 5 new ingestion FRs (FR-31..FR-35) as a side effect of the
  corpus review — those are addressed under D-030, D-031, D-032 plus
  FR-31 / FR-34 batches without their own decisions.
- 7 new heading-classification tests + 1 profiler integration test pin
  the new behavior.

**Related**: FR-3, D-003, D-030, D-031, D-032.

## D-034: Parser hardening — corpus-correctness rules from real-PDF review

**Date**: 2026-05-01
**Status**: Accepted
**Phase**: Development (architectural rules captured retroactively from
the parser-hardening session against the 5 Verizon OA PDFs)

**Context**
User-driven review of `~/work/env_vzw/out/profile/profile.json` and the
parsed trees against the source PDFs surfaced multiple corpus-correctness
bugs in `_build_sections` and adjacent code paths. Each bug had a
specific root cause and a specific fix; consolidated here because they
all shape the parser's contract for handling real-world PDF extraction
artifacts.

**Decision** — five layered rules:

1. **Req-id placement is a corpus property, default `trailing`** (currently
   hardcoded in parser, TODO to move to profile-stage detection). OA
   places small-font req_id blocks AFTER the heading they belong to
   (trailing markers); the parser's pre-fix `pending_req_id` behavior
   (leading markers, where extras lateral to the next heading) produced
   a systematic off-by-one cascade. Now: when a req_id block is
   encountered and `current_section.req_id` is already set, the new id
   is IGNORED with a debug log (first-id-wins) — never lateralled.
   `pending_req_id` only fires when no section has been opened yet.

2. **Table-anchored extraction is deferred to a second pass**. Tables
   are collected during the main walk; table-anchored req extraction
   runs after `paragraph_req_ids` and `struck_req_ids` are fully
   populated. Paragraph anchors and struck ids take precedence over
   table-cell ids regardless of source order. Eliminates the duplicate-
   when-table-precedes-anchor pattern (a req_id whose paragraph anchor
   is on page 34 but who appears in a cross-reference table on page 3
   was getting both nodes).

3. **Heading-continuation defense**. PyMuPDF wraps long headings across
   multiple text blocks; when the continuation line happens to start
   with `<digits><space><uppercase>`, the relaxed numbering gate
   misclassifies it as a phantom depth-1 chapter. Fingerprint (all
   three required): depth-1 section_number + a deeper section already
   seen + previous block was heading-shaped (no body text or req_id
   between). When the fingerprint matches, the new "section" is
   appended to the current section's title as continuation rather than
   creating a phantom chapter.

4. **Req-id whitespace canonicalization**. PDF text extraction
   occasionally fuses bold runs and drops the underscore in
   `VZ_REQ_PLAN_NUM` → arrives as `VZ_REQ_PLAN NUM`. Profile patterns
   accept either separator (`[_\s]\d+`); parser canonicalizes every
   matched id (whitespace → underscore) before storage and comparison
   so the same requirement is never tracked under two identifiers.
   `_canonicalize_req_id` helper + `_find_req_ids` wrap site.

5. **`DocumentProfile.enable_table_anchored_extraction: bool = True`**.
   Default preserves D-027 behavior (back-compat for MNOs that
   genuinely use table-defined reqs). Set to False via the corrections
   workflow for paragraph-only-requirement corpora (Verizon OA): table
   extraction becomes a no-op, eliminating cross-reference / changelog
   table phantoms in one move.

**Why this over alternatives**
- *Per-MNO hardcoded behavior in parser* — rejected. Violates D-003;
  the profile is the single source of corpus-specific rules.
- *Single-pass table extraction with retroactive dedup* — rejected for
  rule 2; the deferred two-pass approach is simpler and order-
  independent. Forward-only single-pass needed an extra reconciliation
  pass anyway.
- *Tighter heading-continuation heuristic* (e.g. require the depth-1
  number to be unrelated to previous) — rejected; the three-part
  fingerprint is precise enough in practice (4/4 confirmed false
  positives caught, no real chapter transitions broken in the OA
  corpus where multi-chapter docs don't exist).
- *Strict req-id pattern (no whitespace)* — rejected; PDF extraction
  artifacts are real and silent ID drops are worse than slightly more
  permissive matching with canonicalization.
- *`enable_table_anchored_extraction` defaults to False (drop D-027 by
  default)* — rejected; D-027 is a real architectural decision about
  multi-MNO support. Defaulting True keeps it on; corpora that don't
  use table-anchored reqs flip the flag via corrections.

**Consequences**
- Parser semantics shift: req-id assignment is now first-id-wins and
  trailing-only (without profile-stage detection of leading-marker
  corpora, the current implementation may misbehave there — see
  Flag 2026-05-01).
- All req_ids stored under canonical underscore form regardless of
  PDF extraction artifacts; consumers comparing ids never need to
  whitespace-normalize.
- Profile schema gains: `requirement_id.placement` (TODO),
  `enable_table_anchored_extraction`. Old profile JSONs load with
  default values intact.
- Empirical corpus result: OA req count 985 (broken A3 baseline) →
  1015 (with `enable_table_anchored_extraction=False`) or 1048
  (default). Phantom duplicates eliminated; off-by-one cascade gone;
  17 ground-truth pairs verified; parse_audit confidence 96%/3%/0.1%.

**Related**: FR-3, D-003 (no per-MNO code), D-027 (table-anchored
extraction architecture), D-031 (strikeout drop), D-033 (numbering-
driven heading classification).


## D-035: Profile-driven revision-history table omission (FR-34)

**Date**: 2026-05-02
**Status**: Accepted
**Phase**: Development

**Context**
OA documents have a revision/change-history table near the top of section 1.
Different MNOs use different headings ("Revision History", "Change History",
"Document Log", etc.) so detection cannot be hardcoded. Tables sometimes
span multiple pages — pdfplumber emits each page's slice as its own table
block.

**Decision**
- New `DocumentProfile.revision_history_heading_pattern: str` field. Default:
  `(?i)^\s*(revision|change|version|document)\s+(history|log)\s*$` — broad
  enough to catch common labels without per-MNO config.
- Profiler narrows the regex during scan to the most-frequent observed
  phrasing (whitespace-tolerant via `re.escape().replace(r"\ ", r"\s+")`),
  gated on the next non-image block being a table.
- Parser drops the matching paragraph, then consumes subsequent table/image
  blocks until the next paragraph (which is by construction the next
  section's heading). New `ParseStats.revhist_blocks_dropped` counter.

**Why this over alternatives**
- *Hardcoded keyword list in parser* — rejected. Violates D-003.
- *Per-corpus profile override only (no broad default)* — rejected. New corpora
  would silently retain revhist tables until someone curates an override.
- *Window-bounded next-block consume (3 blocks)* — initial design; replaced
  when corpus probe revealed revhist tables span multiple pages. Now
  consumes until next paragraph, unbounded by block count.

**Consequences**
- Profile schema gains `revision_history_heading_pattern`. Old profile JSONs
  load with the default intact.
- Parser drops any paragraph matching the pattern PLUS all subsequent
  non-paragraph blocks until the next paragraph.
- env_vzw empirical: `revhist=73` (5 heading paragraphs + 68 continuation
  blocks across 5 docs). Previously 10 with single-table window.

**Related**: FR-34, D-003, D-031.


## D-036: PDF table strike detection — row-edge filter + per-row cell strike

**Date**: 2026-05-02
**Status**: Accepted
**Phase**: Development

**Context**
FR-33 [D-031] geometric strike detection produced 93% false positives on
the OA corpus (709 of 762 tables flagged struck). Probe revealed pdfplumber
draws each row boundary as a horizontal line of full-cell width —
geometrically indistinguishable from a strike-through to `_table_is_struck`.
The `min_lines=2` threshold was protecting nobody: any 3+ row table with
grid lines trivially crossed it.

User feedback also clarified that real strike-throughs in OA tables are
*per-row*: short strike segments cover individual word/text spans inside
specific cells, never spanning the full table width. Whole-table strikes
exist but are rare.

**Decision** — two complementary filters:

1. **Row-edge filter on `_table_is_struck`**. Strike candidates whose y aligns
   with any `Table.rows[*].bbox` edge (within `edge_tol=1.5pt`) are excluded
   from the threshold count. The tolerance handles paired top-of-row-i /
   bottom-of-row-(i-1) draws that some PDF generators emit at adjacent ys.
   Real strike-throughs draw at the *middle* of a text row, well away from
   row boundaries; they survive the filter.

2. **Per-row cell strike via `_detect_struck_rows`**. Walks `table_obj.rows`
   and flags rows whose interior (`y_top + 1.5 < y < y_bot - 1.5`) contains
   ≥1 horizontal strike line. Header row (index 0) is never marked struck
   (OA tables retain their header even when all data rows are deleted).
   Struck rows are dropped from the IR's `rows` list at extraction time;
   if all data rows drop, the whole table is marked `strikethrough=True`
   so the parser drops it via the existing FR-33 path.

**Why this over alternatives**
- *Raise `min_lines` threshold* — rejected. To rule out 3-row grid lines we'd
  need ≥4, which would miss small 2-row genuinely struck tables.
- *Abandon geometric detection on tables* — rejected. Real cell strikes
  (LTEAT p38 KEYPAD CONTROL row) need to be caught somehow.
- *Per-row strike with table-bbox-width gate* — rejected. Real cell strikes
  cover only the cell's text width, not the table's. Counting in row
  interior without horizontal coverage thresholds matches the actual
  geometry pattern.
- *Add per-row strike metadata to IR (preserve rows, mark struck)* — rejected
  for now. Dropping at extraction simplifies the parser-side contract; if a
  future workflow needs to override per-row strikes, the corrections file
  is the seam.

**Consequences**
- `_table_is_struck` signature gains `row_edge_ys: list[float] | None`,
  `edge_tol: float = 1.5`. Caller passes edges from pdfplumber `Table.rows`.
  None/empty preserves legacy behavior (back-compat).
- New `_detect_struck_rows(table_obj, strike_lines, edge_tol=1.5)` returns
  data-row indices to drop. Header excluded.
- Extract-time row drops are silent (no per-row strike marker in IR);
  callers can't recover them.
- env_vzw empirical: tables flagged struck 709/762 → 0/762; row-level drops
  emptied 280 tables (whole-table strikethrough propagated to parser);
  parse_stats.struck_blocks_dropped 1088 → 659 (paragraphs + emptied
  tables).

**Related**: FR-33, D-031.


## D-037: Section-heading cascade for struck headings

**Date**: 2026-05-02
**Status**: Accepted
**Phase**: Development

**Context**
User feedback identified two pages where a struck section heading should
cause its descendants to be dropped even when the descendants themselves
are not individually marked struck:

- LTEB13NAC p310: parent heading `_6289` "LTE Test Application for Antenna
  Testing Requirements" is struck; the (non-struck) TIS table directly
  below it should be dropped as part of the deleted section.
- LTEB13NAC p68: heading `1.3.1.2.7.15 RSSI ...` is struck; the section
  body and any sub-sections under it are also gone in source.

The pre-cascade parser dropped the struck heading paragraph but left
descendant blocks orphaned, attaching them to the previous (live) section
or producing phantom Requirements.

**Decision**
Parser maintains a single `cascade_depth: int | None` state across the
block walk. When a struck paragraph is also a section heading (depth
detected via `_classify_heading` so the cascade boundary uses EXACTLY the
same definition of "heading" as the rest of the parser), `cascade_depth`
is armed to that heading's depth. Subsequent blocks are dropped until a
new heading appears at depth ≤ `cascade_depth` (a sibling or shallower
section), at which point cascade ends and that block is processed normally.
Tables, images, and body paragraphs all get dropped. Deeper-nested struck
headings inside an already-cascading section don't tighten the boundary
(only shallower struck headings do — protects against late corrections
narrowing scope). New `ParseStats.cascade_blocks_dropped` counter.

**Why this over alternatives**
- *Drop only the heading paragraph* — rejected. Leaves orphan tables/sub-
  content under the previous live section.
- *Cascade until next paragraph (no depth check)* — rejected. Would terminate
  cascade on the first body sentence, missing sub-headings and tables that
  belong to the deleted section.
- *Cascade indefinitely (drop everything after a struck heading)* — rejected.
  A depth-5 struck heading would erase its depth-2 siblings.
- *Use the profile's `numbering_pattern` directly for boundary detection* —
  rejected. The pattern's capture-group shape varies per profile;
  delegating to `_classify_heading` reuses the parser's own length-cap and
  punctuation guards.

**Consequences**
- New parser invariant: a struck section heading deletes the entire section
  subtree (down to depth ≤ cascade_depth boundary).
- `ParseStats.cascade_blocks_dropped` reports drops; env_vzw empirical: 301
  blocks dropped across 5 docs.
- Cascade test depends on `_classify_heading`'s definition of heading,
  which means if heading classification changes, cascade boundaries shift
  in lockstep — desirable.

**Related**: FR-33, D-031, D-033.


## D-038: Table-anchored definitions extraction (extends D-032)

**Date**: 2026-05-02
**Status**: Accepted
**Phase**: Development

**Context**
D-032 specified that `_extract_definitions` scans the matched glossary
section's body text line-by-line via `definitions_entry_pattern`. On the
OA corpus, this returned `defs=0` despite all 5 docs having a glossary
section: the section body is a thin intro paragraph ("This section defines
acronyms used throughout the document.") and the actual term/expansion
pairs live in 2-column tables (`Acronym/Term | Definition`,
`Term [Abbreviation] | Definition`, etc.). Body-text scan never sees them.

**Decision**
`_extract_definitions` scans BOTH layouts — body-text via the existing
pattern (preserved unchanged), AND tables. For each row of length ≥ 2 in
the matched section's tables, col[0] is the term and col[1] is the
expansion; whitespace (including embedded newlines from PDF wrap) is
collapsed. First-occurrence-wins precedence applies across both layouts:
body-text scans first, then tables in document order. No profile flag
gates the table path — any 2+ col table inside a glossary section is
treated as a glossary table by convention.

**Why this over alternatives**
- *New profile flag `definitions_layout: str = "body" | "table" | "auto"`*
  — rejected. The two layouts don't conflict (a doc with both gets both),
  and "auto" is what humans want by default. Adding a flag for a no-cost
  combined behavior is over-engineering.
- *Detect column header ("Acronym/Term", "Term", etc.) before treating
  rows as defs* — rejected. Different MNOs use different column headers;
  the structural position (col[0], col[1]) is the reliable signal.
- *Cap term length to filter prose-shaped first-cells* — rejected for
  table layout. The structural gate (must be inside a glossary section's
  table) is strong enough.

**Consequences**
- `_extract_definitions` yields entries from EITHER body text OR tables OR
  both — callers don't need to know which.
- env_vzw empirical: defs=0 → 158. LTEAT 26, LTEB13NAC 63,
  LTEDATARETRY 36, LTEOTADM 18, LTESMS 15.
- Minor extraction artifact: PDF wrap can split "3rd" across lines as
  "rd\n3" → expansion text reads "rd 3 Generation Partnership Project..."
  Term key (`3GPP`) is correct; expansion remains readable. Acceptable
  for v1.

**Related**: FR-35, D-032.


## D-039: Entity-priority graph scoping

**Date**: 2026-05-02
**Status**: Accepted
**Phase**: Development

**Context**
A4 evaluation's `traceability` category scored 16.7% accuracy. trace_01
("What is requirement VZ_REQ_LTEDATARETRY_7754?") returned 10 *other* req
chunks — not _7754 — despite _7754 existing in the graph and vector store.
Trace: the analyzer correctly extracted _7754 as an entity; the graph
scoper's `_entity_lookup` correctly found the node; but `_feature_lookup`
THEN expanded via the DATA_RETRY feature (~700 mapped reqs) into a
794-candidate seed. ChromaDB's `where: req_id IN [794 ids]` filter then
ranks by vector similarity — _7754 didn't make top-10 because the literal
query text isn't semantically close to its chunk content.

**Decision**
When `_entity_lookup` yields any matches, treat those as authoritative for
the scope:
- Skip `_feature_lookup`, `_plan_lookup`, and `_title_search` expansion.
- Step-5 edge traversal (depth=2 from entity seeds) still runs, providing
  the entity's immediate neighborhood — sibling sections, referenced
  standards, parent containers — without flooding the candidate set with
  feature-wide reqs.

For queries WITHOUT specific entity matches (the analyzer extracted
nothing or only false-positive concepts), the existing flow (feature →
plan → title-search → traversal) is unchanged.

**Why this over alternatives**
- *Always merge entity + feature seeds (status quo)* — rejected. Diluted
  the 1-req entity match into a 794-candidate scope where vector ranking
  couldn't surface the named req.
- *Boost entity-match chunks at retrieval time (rerank)* — rejected as
  the primary fix. Reranking is one more knob; the upstream fix (don't
  add the 793 unrelated reqs to the scope) is cleaner. Reranking can be
  added later orthogonally.
- *Bypass vector retrieval entirely when entity matches exist (direct chunk
  lookup by req_id)* — rejected. Loses the neighborhood-context retrieval
  that makes "what is X and how does it relate" queries work.

**Consequences**
- Specific-id queries ("What is VZ_REQ_X?") get tight scope rooted at the
  named req, with depth-2 neighborhood for context.
- Concept queries (no entity match) behave as before.
- env_vzw empirical: trace_01 acc 0% → 100%; traceability 16.7% → 50%
  (then 66.7% after ground-truth refresh).

**Related**: FR-22 (graph-scoped retrieval), D-002 (unified store with
metadata filters).


## D-040: Type-aware retrieval `top_k` + cross-doc list-style detection

**Date**: 2026-05-02
**Status**: Accepted
**Phase**: Development

**Context**
A4 evaluation's `cross_doc` category scored 0% accuracy on all 4 questions
("What are all the SMS over IMS requirements?" / "What are the PDN
connectivity requirements across all VZW plans?" etc.). Investigation
revealed two compounding issues:

1. **Misclassification.** `_classify_query_type` only flagged `CROSS_DOC`
   when ≥2 plan aliases appeared in the query — a high bar that misses
   concept-shaped breadth questions. cross_01 was classified `SINGLE_DOC`.

2. **Insufficient `top_k`.** List/breadth questions expect parent or
   overview reqs (e.g., `VZ_REQ_LTESMS_30258` "SMS OVER IMS - OVERVIEW",
   chunk len ~280 chars: heading + path only) whose chunks are
   intentionally short. Vector similarity ranks them below richer leaf
   chunks (663 chars of body). With `top_k=10`, expected reqs land at
   rank #15+. Probed distances on cross_01:
   ```
   top-10 range:    0.314–0.372
   expected reqs:   0.383, 0.386, 0.577 (just outside)
   ```

**Decision** — two coupled fixes:

1. **Analyzer adds list/breadth phrase triggers**. `_classify_query_type`
   gains an explicit pre-multi-plan-alias check on phrases:
   `across all`, `across the`, `in all`, `across vzw|mnos|plans|specs`,
   `all the requirements`, `all reqs`, `what are all`, `what requirements`.
   These map to `CROSS_DOC`. FEATURE_LEVEL still wins on more-specific
   phrasing ("everything about", "related to") so the existing
   classification contract holds (FEATURE_LEVEL > CROSS_DOC ordering).

2. **`QueryPipeline` picks `top_k` from `_TYPE_TOP_K`** based on
   `intent.query_type`:
   - CROSS_DOC / FEATURE_LEVEL / STANDARDS_COMPARISON /
     CROSS_MNO_COMPARISON → 25
   - TRACEABILITY / RELEASE_DIFF → 20
   - SINGLE_DOC / GENERAL → fall through to constructor `self._top_k`
     (default 10)

   Pipeline takes `max(self._top_k, type_top_k)` so callers can still
   raise the floor explicitly.

**Why this over alternatives**
- *Uniform top_k=20 for all queries* — rejected. Wastes context on lookup-
  style queries that are already well-served by 10. Per-type tuning costs
  almost nothing and isolates the regression risk.
- *Analyzer-driven top_k (set in QueryIntent)* — considered but more
  surface area than needed. The pipeline knows the intent; encoding
  top_k in the QueryIntent dataclass would couple the schema to retrieval
  config. Keeping it in the pipeline keeps the analyzer's job pure.
- *Boost short/parent chunks at rerank time* — rejected as the primary
  fix. Same logic as D-039: upstream fix (more headroom) is simpler than
  reranking. Rerank stays orthogonal.
- *Raise CROSS_DOC bar to ≥1 plan alias instead of ≥2* — rejected. False
  positives multiply (any mention of "LTE" or "SMS" would trigger). The
  list/breadth phrase set is more precise.

**Consequences**
- New `_TYPE_TOP_K` constant in `query/pipeline.py`. Map values are
  tuneable knobs, not architectural commitments.
- Cross-doc queries cost more LLM tokens (more chunks → larger context).
  Manageable: qwen3-235b-a22b has 128k context; 25 chunks × ~500 chars
  is well under.
- env_vzw empirical: cross_doc 0% → 37.5%; overall avg_accuracy
  56.5% → 64.8%; no regression in single_doc (still 79%).

**Related**: FR-22, D-039 (entity-priority scoping — companion fix for
the lookup side).


## D-041: BM25 hybrid retrieval — sparse index, RRF fusion, per-type weights

**Date**: 2026-05-02
**Status**: Accepted
**Phase**: Development

**Context**
A4 evaluation showed pure-dense retrieval missed concept queries with
specific high-IDF terms. `standards_comparison` was at 50% accuracy
because queries like "How does VZW T3402 differ from 3GPP TS 24.301?"
have rare terms (`T3402`, `24.301`) that pure-dense embeddings spread
thin across many topically-related chunks. The expected reqs existed
in the graph and vector store but ranked outside top-k.

A purely-dense system has no good way to surface these. BM25 over
chunk text is the textbook complement — it weights rare exact terms
by IDF, so `T3402` (occurring in 1-2 of 794 chunks) ranks the
matching chunks above topically-broader matches.

**Decision** — five layered choices:

1. **Add `rank_bm25.BM25Okapi` as the sparse retriever**. Pure-Python,
   no compilation, ~10KB wheel. Sufficient for corpus sizes through
   the v1 multi-MNO scope (~10k chunks max).

2. **Build the index in-memory at `QueryPipeline` init time** from a
   one-shot `store.get_all()` snapshot. ~50-100ms for 794 chunks; fits
   the cost of a CLI/process startup. Persistence would add a build
   step + a stale-index-vs-store contract; not worth the complexity
   at this corpus size.

3. **Custom telecom-aware tokenizer**. Standard tokenizers split on
   underscores/dots/hyphens, breaking the corpus's most discriminating
   tokens (`vz_req_lteat_45`, `24.301`, `rel-9`) into uninformative
   sub-tokens. Pattern: `[a-z0-9_.\-]+` lowercase, drop len-1 tokens.
   No stemming (telecom acronyms don't stem), no stopword filtering
   (BM25's IDF already penalizes common words).

4. **Reciprocal Rank Fusion (RRF) with per-list weights**, k=60
   (Cormack 2009). Chosen over score normalization because BM25 raw
   scores and dense distances aren't on comparable scales; rank-based
   fusion sidesteps the issue. Weighted variant
   `score(d) = Σ w_i / (k + rank_i(d))` lets dense dominate when the
   query type doesn't benefit from BM25.

5. **Per-query-type BM25 weights**, configured in
   `pipeline._TYPE_BM25_WEIGHT`:
   - `STANDARDS_COMPARISON` / `TRACEABILITY` / `SINGLE_DOC` → 0.5
   - `CROSS_DOC` / `FEATURE_LEVEL` (and unmapped types) → 0.0 (pure
     dense)
   Empirically: BM25 hurts cross-doc / breadth queries because the
   expected hits are thin parent/overview chunks that BM25 ranks low;
   richer leaf chunks dominate the fusion. CROSS_DOC went 37.5%→8.3%
   when BM25 fired uniformly at 0.5; per-type policy preserves the
   gain on standards / traceability without the regression elsewhere.

**Why this over alternatives**
- *Always-on uniform BM25 weight* — rejected. Regressed cross-doc
  by 29pp; the parent/overview-chunk problem is real and corpus-
  shape-dependent.
- *Persisted BM25 index alongside ChromaDB* — rejected for v1.
  Build cost is negligible at corpus scale; persistence adds a
  stale-vs-store contract to maintain.
- *Off-the-shelf tokenizer (NLTK / sklearn)* — rejected. Splitting
  `vz_req_lteat_45` into `vz / req / lteat / 45` discards the most
  important token signal in the corpus.
- *Score normalization + linear combination* — rejected over RRF.
  BM25 scores are corpus-size-dependent and dense distances are
  metric-specific; normalizing them to a comparable scale is
  brittle. RRF is rank-based and parameter-free aside from `k`.
- *Cross-encoder reranker on dense top-k* — deferred (see Next).
  Higher leverage but heavier lift (model selection, latency
  budget, training data); BM25 was the cheap win to capture first.

**Consequences**
- `VectorStoreProvider` protocol gains `get_all() -> QueryResult`
  with empty `distances`. Existing implementers need to add it;
  back-compat preserved by the optional `from_store(store)`
  fallback in `BM25Index` returning None when the method is absent.
- `RAGRetriever` constructor accepts optional `bm25_index`; the
  `retrieve()` signature gains optional `bm25_weight: float | None`
  for per-call override. None / 0.0 / `bm25_index=None` all
  short-circuit to pure-dense (back-compat, perf when not needed).
- BM25 filter must use `metadata.req_id` (not `chunk_id`) to gate
  candidates — chunk_ids are `req:<req_id>` while the dense path
  filters on the metadata field. Mismatched filter spaces produce
  empty BM25 results; learned the hard way during integration.
- `_TYPE_BM25_WEIGHT` is empirical tuning, not architectural
  contract. Numbers will shift as the eval set grows; treat as
  hyperparameter, not invariant.
- Empirical impact on env_vzw: standards_comparison 50%→83.3%
  (+33pp); traceability +16.7pp via the companion `mention`
  classifier route; overall accuracy 67.6%→73.1% (+5.5pp from
  BM25 alone).

**Related**: D-001 (KG-scoped RAG), D-002 (unified vector store),
D-039 (entity-priority graph scoping — companion fix for the
specific-id lookup path), D-040 (per-type top_k + cross-doc
detection — the existing companion that BM25 was layered onto).


## D-042: Parent-chunk subsection augmentation — opt-in, default off

**Date**: 2026-05-02
**Status**: Accepted
**Phase**: Development

**Context**
After BM25 hybrid retrieval landed, A4 still had concept queries
where the right req existed in the corpus but didn't rank in
top-k. Hypothesis: parent/overview chunks (`SMS over IMS - OVERVIEW`,
`DETACH REQUEST`, etc.) lose to richer leaf chunks because their
own bodies are heading-only — a query about "SMS over IMS
requirements" has a rich-body chunk about MO-SMS-procedure outranking
the literal "SMS over IMS - OVERVIEW" parent.

Mooted fix: augment parent chunks with their immediate children's
titles so the parent's chunk text gains breadth-relevant tokens
without changing the leaf chunks. Tested empirically.

**Decision**
Implement the augmentation as a chunk-builder feature, ship default
**off**, expose three config knobs for opt-in tuning:

- `VectorStoreConfig.include_children_titles: bool = False`
- `VectorStoreConfig.children_titles_body_threshold: int = 300` —
  body-thinness gate (only parents with `len(body) < threshold` get
  augmented)
- `VectorStoreConfig.max_children_titles: int = 3` — cap on the
  emitted list with `(+N more)` overflow marker

When enabled, `_build_chunk_text` appends a single line:
`[Subsections: child1; child2; (+N more)]` after the body / tables /
images.

**Why default off** — empirical tuning on env_vzw (BM25 hybrid +
per-type top_k baseline = 88.9% / 80.1%):

  Augmentation on, cap=12: 88.6% / 78.8% (single_doc +8pp,
    cross_doc -14pp — net -1.3pp accuracy)
  Augmentation on, cap=3:  88.8% / 79.7% (single_doc +8pp,
    cross_doc -10pp — net -0.4pp accuracy)
  Augmentation off:        88.9% / 80.1% (baseline)

Body-thinness gate doesn't selectively help on OA: 89% of parents
have body<50 chars (heading-only), 94% are <300. The gate's
selectivity is corpus-shape-dependent.

The single_doc gain is real (parents become findable for "find
this section" queries) but the cross_doc loss is structurally the
same effect from the other side — augmented parents displace their
own children from top-k, and breadth queries explicitly want the
children. The two effects offset.

**Why this over alternatives**
- *Augment unconditionally (default on)* — rejected. -1.3pp
  accuracy regression on the eval the user just curated.
- *Per-query-type augmentation in retrieval (use augmented chunks
  for SINGLE_DOC, plain chunks for CROSS_DOC)* — rejected for v1.
  Would require dual-indexing (two embedding sets per chunk) or
  retrieval-time text manipulation; both add surface area for a
  feature that's a wash.
- *Augment but don't include in the embedded text — only in the
  chunk metadata* — rejected. Metadata isn't searched by the
  embedder or BM25; the augmentation has no effect.
- *Drop the feature entirely* — rejected. Implementation cost is
  paid; the principled hypothesis is sound; corpora with rich-
  bodied parents (less heading-only) should benefit; lookup-heavy
  question mixes should benefit. Keep it behind a flag for those
  cases; document the tradeoff so future evaluators don't flip it
  blind.

**Consequences**
- New config surface stays back-compat (default-off preserves
  prior chunk text exactly).
- `ChunkBuilder._build_chunk_text` signature gained an optional
  `id_to_title: dict[str, str] | None` param; `_build_tree_chunks`
  builds the lookup once per tree.
- 8 new tests pin the contract: emit-when-enabled, suppress-when-
  disabled, cap behavior, overflow marker, unresolved-child-id
  defense, body-thinness gate fires correctly on both sides.
- Future eval re-runs on TMO / AT&T corpora are the right
  trigger to re-evaluate the default. If their parent sections
  carry substantive body content (less heading-only than OA), the
  augmentation tradeoff likely flips positive and the default
  could be flipped to on.

**Related**: FR-3 (profile-driven generic parser produces the
hierarchy this consumes), D-027 (table-anchored Requirements that
make some "parents" thin), D-040 (per-type top_k — interacts with
augmentation because wider top_k gives more room for both parents
and children to coexist).


## D-043: Acronym lookup chain — parser fix + glossary chunks + query-side pin

**Date**: 2026-05-03
**Status**: Accepted
**Phase**: Development

**Context**
A user-submitted question on the Test page — *"What is SDM?"* —
returned a hallucinated definition ("SIMOTA Device Management
server"). The corpus glossary in fact defines SDM as "Subscriber
Device Management — APN Management and Device profiling" in the
LTEOTADM document. Three independent failures stacked:

1. The parser's `definitions_map` was missing SDM (18 of 19
   acronyms extracted). Markdown extractors split the glossary
   into two tables when a divider line (`|---|`) appears mid-
   table; the row immediately after the divider lands in
   `tbl.headers`, not `tbl.rows`. `_extract_definitions` only
   walked rows, so SDM was silently dropped.
2. Even with the chunk text containing the acronym, retrieval
   couldn't rank it for *"What is SDM?"*. The glossary chunk is
   dominated by 18 other acronyms; BM25 weights the chunk with
   the most "SDM" mentions (an operational chunk), and dense
   similarity for a 4-token query is noisy.
3. No mechanism to let the system route definitional queries
   directly to glossary entries.

**Decision**
Implement a three-layer fix; ship all three together because any
one alone is insufficient.

**A. Parser** (`structural_parser._extract_definitions`)
- Walk `tbl.headers` in addition to `tbl.rows`.
- Filter the canonical column-header row via a token-set check:
  both columns' headers must be entirely from a known canonical
  set (`acronym, term, definition, abbreviation, meaning,
  description, …`) to be treated as a real header. Otherwise
  fold them into the candidates list.
- VZW LTEOTADM `definitions_map`: 18 → 19 entries.

**B. Glossary chunks** (`vectorstore.chunk_builder._build_glossary_chunks`)
- Each entry in `definitions_map` becomes its own chunk:
  - `chunk_id = "glossary:<plan_id>:<acronym-slug>"` —
    slug strips non-`[A-Za-z0-9_-]+`.
  - `metadata.doc_type = "glossary_entry"`,
    `metadata.{acronym, expansion}` populated.
  - Text leads with `<ACRONYM>: <expansion>` so BM25 (high TF)
    and dense (concise definition) both rank it top for short
    acronym queries.
- These are *additional* to the requirement chunk for the
  definitions section, not a replacement.

**C. Glossary pin** (`query.rag_retriever`)
- `_ACRONYM_QUERY_RE` matches: "What is X", "What does X mean",
  "What does X stand for", "Define X", "Definition of X",
  "Meaning of X", "Expand acronym X" / "Expand X".
  X = 2-15 chars, first char letter, rest letters/digits/dash/
  underscore. Case-insensitive.
- `RAGRetriever.__init__` builds `_glossary_by_acronym` once by
  scanning `store.get_all()` for `doc_type=glossary_entry`
  chunks. Empty on pre-D-043 corpora (back-compat).
- `retrieve()` runs normal retrieval (graph scope → BM25+dense →
  rerank → diversity) FIRST, then if the regex matches AND the
  acronym is in the index, prepends matched glossary chunks
  with dedup-by-chunk-id, and trims back to top_k.
- Pin runs *after* the cross-encoder so the encoder doesn't
  demote a chunk we know is the answer.

**Why this over alternatives**
- *Augment retrieval with a synthetic acronym field instead of a
  separate chunk* — rejected. Would require dual-indexing
  (acronyms vs body) or per-query field weighting; adds surface
  area without obviously winning over the deterministic pin.
- *Boost glossary chunks via a score multiplier in
  `_TYPE_BM25_WEIGHT`-style policy* — rejected. Score-boosting is
  fragile (depends on score distribution) and doesn't solve the
  case where the glossary chunk doesn't make the candidate cut.
- *LLM-side fix only — let the synthesizer query a definitions
  service* — rejected. Adds an LLM call per acronym query,
  doubles latency, and removes citations (the corpus chunk *is*
  the citation surface).
- *Parser fix only* — rejected per §1.2-3 above; necessary but
  not sufficient.

**Consequences**
- New `Citation.llm_cited: bool` flag (default False) lets
  callers separate LLM-extracted citations from context-fallback
  citations. Eval keeps the legacy aggregate count via
  `len(response.citations)` — the new field is purely additive.
- New `QueryResponse.retrieved_chunks: list[RetrievedChunk]`
  surfaces the post-Stage-4 retrieval set so the Test page can
  render "Returned by RAG" alongside "Cited by LLM". Off the LLM
  hot-path.
- `RAGRetriever.__init__` reads from the store at construction
  time. With the pipeline cache on `app.state` (see web routes),
  this happens once per process.
- 13 new tests (3 parser + 3 chunk-builder + 7 retriever
  glossary-pin scenarios) pin the contract: regex coverage,
  unknown-acronym fall-through, non-acronym queries skipped,
  dedup, back-compat with empty index, slug safety for
  acronyms with spaces / punctuation.
- Future corpora benefit automatically — any plan whose
  `definitions_map` contains an acronym gets a glossary chunk
  AND becomes pin-eligible.

**Related**: D-032 (per-document definitions_map + chunk-build
inline expansion), D-038 (table-anchored definitions extraction),
D-041 (BM25 hybrid — pin runs after fusion). See
[`core/src/query/RETRIEVAL.md`](../../core/src/query/RETRIEVAL.md)
for the end-to-end retrieval architecture in which this lookup
chain sits.


## D-044: Unified LLM/embedding config — `config/llm.json` + uniform 3-tier resolution

**Date**: 2026-05-04
**Status**: Accepted
**Phase**: Development

**Context**
LLM and embedding settings were scattered across four surfaces:
- `EnvironmentConfig` fields (`model_provider`, `model_name`,
  `model_timeout`, `embedding_provider`, `embedding_model`) on
  `environments/<name>.json`.
- `WebConfig` fields (`ollama_url`, `default_model`) on
  `config/web.json`.
- Per-knob env vars (`NORA_LLM_PROVIDER`, `NORA_LLM_MODEL`,
  `NORA_LLM_BASE_URL`, `NORA_LLM_API_KEY`, `NORA_EMBEDDING_PROVIDER`,
  `NORA_EMBEDDING_MODEL`, `NORA_OLLAMA_TIMEOUT_S`).
- CLI flags on `pipeline/run_cli.py` (`--llm-provider`,
  `--model`, `--model-timeout`, `--embedding-provider`,
  `--embedding-model`).

The dispersion meant: machine-specific defaults landed in tracked
env-config files (problem for teammates committing their personal
paths); web and pipeline read different sources for the same
"what LLM should we use?" question; the documented precedence
order varied per knob; and adding a new knob required edits in
five places.

**Decision**
One canonical home, one resolution rule:

- **File**: `config/llm.json` (tracked template, empty defaults).
  Fields: `llm_provider`, `llm_model`, `llm_timeout`, `llm_base_url`,
  `llm_api_key`, `embedding_provider`, `embedding_model`,
  `ollama_url`, `ollama_timeout_s`, `skip_taxonomy`, `skip_graph`.
  Loaded once per process via `LLMConfigFile.load()` (cached).

- **Resolution chain (per field, highest priority first)**:
  1. CLI flag (`--llm-provider`, `--model`, …).
  2. Env var (`NORA_LLM_PROVIDER`, `NORA_LLM_MODEL`, …).
  3. `config/llm.json` field.
  4. Built-in default.

  Each `resolve_*` function in `core/src/env/config.py` walks the
  chain in this exact order and returns on the first non-empty value.

- **Back-compat**: legacy `EnvironmentConfig` LLM/embedding fields
  remain a fallback **below** `config/llm.json` (so existing
  `environments/env_vzw.json` still works) with a log line
  documenting deprecation. Removable in a future release once
  user envs have migrated.

**Why this over alternatives**
- *Keep settings spread across `WebConfig` + `EnvironmentConfig`*
  — rejected. Adding a new LLM knob requires edits in both files,
  duplicate validation, and inconsistent precedence (web reads
  one path, pipeline reads another for the same question).
- *Merge into `config/web.json`* — rejected. Web-specific
  settings (host, port, root_path, path_mappings) are unrelated
  to "what LLM is the project using?" and tying them couples
  unrelated lifecycles.
- *Flat env-var-only config* — rejected. Twelve knobs is too
  many env vars for a clean shell prompt; users want a file
  they can edit + check into a personal setup script.
- *Strict 3-tier (drop env-config back-compat entirely)* —
  rejected for v1; would force teammates to migrate their
  existing `environments/<name>.json` files in lockstep with
  this commit. Deferred until a major-version bump.

**Consequences**
- One new tracked file (`config/llm.json`); empty defaults so
  fresh clones are unaffected unless the user opts in.
- Each `resolve_*` in `core/src/env/config.py` walks 4 tiers
  (CLI → env var → config/llm.json → env-config back-compat) and
  returns the first non-empty value.
- New `LLMConfigFile` dataclass + module-level cache + test
  `_reset_llm_config_cache()` hook.
- Module-level constants `DEFAULT_LLM_CONFIG_PATH`,
  `SKIP_TAXONOMY_ENV_VAR`, `SKIP_GRAPH_ENV_VAR`, `RAG_ONLY_ENV_VAR`
  added to the env module's public surface.
- 11 new tests pin the per-field resolution chain (CLI beats env
  var beats config beats env-config beats default for
  `llm_provider`; analogous pins for `embedding_provider`,
  `embedding_model`, `skip_taxonomy`, `skip_graph`,
  `NORA_RAG_ONLY` implies both).
- README config table consolidates 5 prose subsections into one
  19-row, 4-column reference (commit babd9f0).

**Related**: D-022 (per-env runtime directory; settings scoped to
the env vs settings global to the install — `config/llm.json` is
intentionally the latter), D-045 (RAG-only mode shares the same
3-tier resolution shape for `skip_taxonomy` / `skip_graph`).


## D-045: RAG-only pipeline mode — skip taxonomy + graph, stub-graph fallback at query time

**Date**: 2026-05-04
**Status**: Accepted
**Phase**: Development

**Context**
The pipeline assumes a full nine-stage build: extract → profile →
parse → resolve → taxonomy → standards → graph → vectorstore →
eval. Two stages — taxonomy and graph — make every run depend on
LLM-derived feature mappings (taxonomy) and a constructed
`networkx.DiGraph` (graph). This is structurally fine but operationally
heavy:

- The taxonomy LLM is the dominant source of run-to-run
  non-determinism (A8 variance experiment showed up to 6.7pp
  spread across three runs on the same vectorstore).
- For concept-shaped queries (cross_doc, standards_comparison)
  the graph scoping in Stage 3 of the query pipeline can do more
  harm than good — it shrinks the candidate pool to a feature-
  mapped subset, occasionally excluding the correct chunk that
  RAG would otherwise rank high.
- A user wanting to A/B "what does retrieval look like without
  the graph?" had no way to answer that without manually deleting
  artifacts and writing a stub.

A baseline-comparison option that pipes around taxonomy + graph
without rewriting the pipeline is a real need.

**Decision**
Add a runtime mode that skips the two stages and makes the rest
of the pipeline tolerate their absence.

- **Three knobs, parallel 3-tier resolution** (per D-044's chain):

  | Knob | CLI | Env var | `config/llm.json` |
  |---|---|---|---|
  | `skip_taxonomy` | `--skip-taxonomy` | `NORA_SKIP_TAXONOMY=1` | `skip_taxonomy: true` |
  | `skip_graph` | `--skip-graph` | `NORA_SKIP_GRAPH=1` | `skip_graph: true` |
  | both at once | `--rag-only` | `NORA_RAG_ONLY=1` | (set both fields) |

  Existing `EnvironmentConfig.skip_taxonomy` (D-040 era) gains a
  parallel `skip_graph: bool = False` field for env-config
  back-compat below the new file.

- **Pipeline-side**: `pipeline/run_cli.py` stage-filter drops
  `taxonomy` and/or `graph` from the run list when the corresponding
  knob is on.

- **Query-side**: `core/src/query/pipeline.py` gains
  `build_stub_graph_from_store(store) -> nx.DiGraph` which derives
  a minimal MNO/Release/Plan-only graph from chunk metadata. Both
  the web `/test` route and the eval stage detect missing
  `<env_dir>/out/graph/knowledge_graph.json` and:
    1. Build the stub via `build_stub_graph_from_store`.
    2. Construct `QueryPipeline(graph=stub, …)`.
    3. Set `pipeline._bypass_graph = True` so Stage 3 emits an
       empty `CandidateSet`.
    4. Stage 4 (`RAGRetriever.retrieve`) routes to the metadata-
       only path (`_retrieve_metadata`) — filters by MNO/release
       only, no candidate-req-id gate.
  EvalRunner picks up the bypass via its existing
  `run_all(questions, bypass_graph=True)` hook from D-001 era.

**Why this over alternatives**
- *Pure runtime flag (no stage-filter)* — rejected. Building a
  graph nobody will read wastes a stage's worth of LLM calls and
  ~30s of compute on every run.
- *Drop `_bypass_graph` and let the resolver/scoper handle a
  None graph* — rejected. Resolver depends on graph for available-
  MNO/release discovery; making graph nullable cascades type
  changes through five files. Stub graph is cheap (~3 nodes, ~2
  edges for env_vzw) and keeps every existing constructor working.
- *Make RAG-only the default* — rejected for v1. Graph scoping
  is a known win on lookup-shaped queries (D-039 entity priority);
  the empirical question of which mode wins per category is what
  the new flag exists to answer.
- *Build the stub at vectorstore stage time, not lazily at query
  time* — considered. Lazy is better because:
    a. Vectorstore stage currently has no graph dependency; adding
       one would couple a previously-clean module boundary.
    b. The stub construction is fast (~milliseconds for env_vzw
       scale) so caching it on disk has negligible benefit.
    c. Lazy means the stub auto-updates if the vectorstore changes
       without requiring a separate "stub-rebuild" step.

**Consequences**
- New invariant exception in `core/src/query/MODULE.md`: the
  "Graph-first, then RAG" rule (D-001) is suspended when
  `pipeline._bypass_graph = True`. Documented inline.
- Eval results in RAG-only mode are NOT directly comparable to
  full-pipeline baselines — Stage 3 is a different filter (or
  no filter). New baselines need their own A-letter labels in
  STATUS.md.
- `_run_query_sync` on the web side previously errored on missing
  graph file ("Knowledge graph not found at …"); the early exit
  is removed, replaced with the stub-graph fallback.
- `_build_pipeline` in `routes/query.py` switches from
  hardcoded `SentenceTransformerEmbedder` to `make_embedder(
  vs_config)` factory — needed because RAG-only with Ollama-
  built vectorstores (e.g. `qwen3-embedding:4b`) was unreachable
  through the old path. (Caught and fixed mid-session — error
  was "Repo id must use alphanumeric chars" because HF prefixed
  the Ollama model name with `sentence-transformers/`.)
- 4 new tests pin the stub-graph contract: emits the right node
  types per metadata, wires `has_release` / `contains_plan`
  edges, omits Requirement / Feature / Standard nodes, and an
  end-to-end QueryPipeline+stub+`_bypass_graph=True` returns
  chunks for a query.
- Future per-corpus tuning: corpora with rich-bodied parents and
  lookup-heavy questions should keep graph mode on; corpora with
  thin parents and concept-heavy questions are candidates to
  flip RAG-only on by default.

**Related**: D-001 (graph-routes-then-RAG; this is the explicit
exception), D-039 (entity-priority graph scoping; only useful
when graph is on), D-040 (per-type top_k; both modes use it),
D-041 (BM25 hybrid; works in both modes), D-044 (unified LLM
config; this decision uses the same 3-tier shape for its
knobs).

---

## D-046: Document-rooted hierarchy paths in chunks (text + metadata)

**Date**: 2026-05-05
**Status**: Accepted
**Phase**: Development

**Context**
Pre-D-046, `chunk_builder` emitted `[Path: SCENARIOS > ATTACH]`
on chunk text — section path within the document, no document
identifier in the path string. The full Document > Section >
Subsection chain wasn't anywhere on the chunk: the embedder
only saw "SCENARIOS > ATTACH", and the retrieval-side context
builder had to walk back to the graph node to recover which
document the chunk came from.

This caused two problems:
- Embeddings for chunks from different documents that happened
  to share a section title clustered together. "ATTACH" reqs
  from LTEDATARETRY and LTEOTADM were near-duplicates in vector
  space because the embedded text was identical structurally.
- Retrieval-side grouping (the eventual Step 3 hierarchy
  grouping) needed to read paths from somewhere structured.
  Reading from the graph forced a graph dependency on the
  grouping logic; reading from chunk text required parsing the
  `[Path: ...]` line back out of free-form text.

**Decision**
Two coupled changes:

- **In chunk text**: prepend `plan_name` (or `plan_id` fallback
  when `plan_name` is empty) as the root segment of the
  `[Path: ...]` line. Output: `[Path: LTEDATARETRY > SCENARIOS
  > ATTACH]`. Disabled when `include_hierarchy_path=False`.
  Suppressed entirely when both `plan_name` and `plan_id` are
  empty AND the requirement's hierarchy is empty.

- **In chunk metadata**: store the full path as a `list[str]`
  under the `hierarchy_path` key on every chunk's metadata
  dict (requirement chunks AND glossary chunks). Always
  populated; `include_hierarchy_path` only gates the text
  prefix, not the metadata. Glossary chunks store
  `[doc_root]` (single-element list).

`context_builder._enrich_chunk` prefers the chunk-metadata
path; falls back to the graph node's `hierarchy_path` when
the metadata is absent (back-compat for vectorstores built
before D-046).

**Why this over alternatives**
- *Path in text only, not metadata* — rejected. Forces
  retrieval-side grouping to parse free-form chunk text. Brittle
  if the prefix line ever changes shape (e.g. when the MNO
  header or req_id line is reordered).
- *Path in metadata only, not text* — rejected. The embedder
  loses the structural signal. The whole point is for the dense
  vector to encode "this chunk is from document X about topic Y"
  not just "this chunk is about topic Y".
- *Use plan_id everywhere (not plan_name)* — rejected. plan_id
  is opaque (`LTEDATARETRY`); plan_name is human-readable
  (`LTE Data Retry`). Embeddings benefit from the natural
  language form. plan_id remains the fallback when plan_name
  is missing.
- *Include the full hierarchy chain in chunk text already* —
  was already the case for hierarchy below the document; this
  decision only adds the document root above it.

**Consequences**
- **Vectorstore must be rebuilt** to surface the new metadata
  field on existing data. Old vectorstores work — context
  builder falls back to the graph node — but they won't get
  the embedding-quality benefit until rebuilt.
- ChromaDB metadata supports `list[str]` values, so the path
  stores natively. They can't be used in `where=` equality
  filters but read-back works fine.
- New `_build_chunk_text` parameter `plan_id: str = ""` with
  the corresponding call-site update in `_build_tree_chunks`.
- 11 new tests in `core/tests/test_chunk_builder_hierarchy.py`
  pin: text format, plan_id fallback, both-empty suppression,
  metadata always-present (independent of text flag),
  glossary-chunk root.
- Existing `test_vectorstore.py::test_chunk_text_has_hierarchy_path`
  updated for the new `LTE_DATARETRY > ROOT > Section 2 Title`
  format.
- Verified live: env_vzw chunks show paths like
  `['LTE_ATCommands_For_Test_Automation', 'LTE AT commands for
  Test automation']`.

**Related**: D-001 (graph + RAG hybrid; this strengthens RAG by
giving embeddings document-level structure), D-038 (definitions
extraction; glossary chunks now also carry the metadata path),
D-043 (acronym lookup chain; glossary chunks were the unit
introduced there, this adds doc-root metadata to them), D-047
(threshold filter consumes the same chunk metadata for the
"not found" path).

---

## D-047: Relevance threshold + "not found" response (Stage 4.5)

**Date**: 2026-05-05
**Status**: Accepted
**Phase**: Development

**Context**
Off-topic queries ("recipe for chocolate cake") still produced
synthesized answers because the LLM was given Stage-4 retrieval
even when every chunk was a weak distance match. Empirical
sweep against env_vzw + qwen3-embedding:4b-q8_0:

- Relevant queries (T3402, attach reject): cosine distances
  0.20–0.41
- Off-topic queries (Westphalia, cake): cosine distances
  0.74–0.77

A 0.33-wide gap between the worst relevant and the best
off-topic chunk. The LLM was synthesizing from chunks at 0.75
distance — primary source of confabulated answers on queries
that simply have no good match in the corpus.

The user's stated principle: *"the system shall not pretend it
is an Oracle."* Off-topic queries should return an explicit
"not found" message rather than an LLM hallucination dressed up
in formatting that mimics a cited answer.

**Decision**
New optional Stage 4.5 in `QueryPipeline.query()`:

- New constructor param `max_distance_threshold: float | None
  = None`. None → filter disabled (back-compat).
- After Stage 4 retrieval, drop chunks where
  `similarity_score > threshold`.
- If the filtered list is empty, return a `QueryResponse` with
  the deterministic `_NOT_FOUND_ANSWER` text **without** running
  Stage 5 (context assembly) or Stage 6 (LLM synthesis). This
  saves the LLM call AND prevents the LLM from being given an
  empty context that it would politely confabulate around.
- New `_TYPE_MAX_DISTANCE` dict keyed by `QueryType`, empty for
  now. Reserved for Step 4 (intent classification) where the
  Fact intent will need a stricter threshold than the general
  pipeline default.
- Web pipeline build sets the default to **0.5** with a
  `NORA_MAX_DISTANCE_THRESHOLD` env-var runtime override
  (`off`/`none`/`""` disables; any float overrides). Logs the
  effective value at pipeline-build time.

**Why this over alternatives**
- *Filter inside `RAGRetriever`* — rejected. The retriever is
  generic and shared between query paths (eval, web, CLI). A
  threshold is a query-pipeline policy, not a retrieval
  concern. Keeping it in `QueryPipeline` lets the retriever
  return raw scores and lets the pipeline (which has the query
  type / intent) make the policy decision.
- *Filter inside `ContextBuilder`* — rejected. Context builder
  doesn't know about per-query-type thresholds and would have
  to grow that responsibility. Stage 4.5 (between retrieval and
  context assembly) is the natural place.
- *Use a similarity score (1 - distance) instead of distance* —
  considered. Would let users think in "min similarity" terms
  (higher = stricter), which matches their mental model better
  than "max distance" (lower = stricter). Rejected for now to
  keep `similarity_score` field semantics stable across the
  codebase; flipping the field at this point would change UI
  display values that users have already seen. Revisit if a
  cleaner abstraction emerges.
- *Per-vectorstore threshold (stored in the saved config.json
  next to chroma data)* — considered. Threshold is calibrated
  to the embedding model + corpus, so co-locating it with the
  vectorstore is logically clean. Rejected for v1 because no
  existing code reads back from the saved config at query
  time, and adding a path felt premature for a single tuning
  value. Promote to that scheme if/when multiple vectorstores
  with different models coexist in one process.
- *Hard-fail with an exception* — rejected. The "not found"
  outcome is a normal answer in the user's workflow, not an
  error. Returning `QueryResponse` keeps the call site uniform.

**Consequences**
- **Threshold is model-specific.** Default 0.5 is pinned to
  qwen3-embedding:4b-q8_0 on the OA corpus. Switching the
  embedding model requires a re-sweep. Flagged in STATUS.md.
- New public field on `QueryPipeline.__init__`; new module-
  level constants `_NOT_FOUND_ANSWER`, `_TYPE_MAX_DISTANCE`.
- 13 new tests in `core/tests/test_query_threshold.py` pin:
  threshold disabled (back-compat), all-above, all-below,
  mixed, exactly-at-threshold, just-above-threshold,
  not-found shape (intent carried, candidate count carried,
  no citations, message non-empty), strict/lenient sweeps.
- Web wiring (`core/src/web/routes/query.py`) adds the helper
  `_resolve_max_distance_threshold` reading
  `NORA_MAX_DISTANCE_THRESHOLD` and logs the effective value
  at pipeline-build time.
- `_TYPE_MAX_DISTANCE` is the seam Step 4 will populate for
  per-intent overrides — Fact intent will get a stricter cap.

**Related**: D-046 (chunk metadata; threshold reads
`similarity_score` populated alongside the new
`hierarchy_path`), D-040 (per-type top_k; per-type threshold
mirrors the same shape), D-041 (BM25 hybrid; threshold is
applied after fusion + diversity, not per-component).

---

## D-048: `vectorstore_cli` `--config <path>` replaces `config/llm.json` (Option A precedence)

**Date**: 2026-05-05
**Status**: Accepted
**Phase**: Development

**Context**
`vectorstore_cli`'s `_build_config` previously knew nothing
about `config/llm.json` — it read `--config <path>` if given
and fell back to its own dataclass defaults otherwise. Users
setting `embedding_model: qwen3-embedding:4b-q8_0` in
`config/llm.json` were surprised when `vectorstore_cli` still
defaulted to `sentence-transformers/all-MiniLM-L6-v2`. The
pipeline runner (`run_cli.py`) honored `config/llm.json`; the
standalone vectorstore CLI didn't, so the two diverged on the
"which embedding model is the project using?" question.

Wiring `config/llm.json` into `vectorstore_cli` was
straightforward — the existing `resolve_embedding_provider` /
`resolve_embedding_model` helpers in `core/src/env/config.py`
already implement the canonical 3-tier rule
(CLI > env > config/llm.json > default). The interesting
question was: how should `--config <path>` interact with
`config/llm.json`?

Two options were on the table:

- **Option A (chosen).** `--config <path>` *replaces*
  `config/llm.json` at the config-file tier. Precedence:
  CLI > env > (`--config` if supplied, else `config/llm.json`)
  > default.
- **Option B.** `--config <path>` is just another value
  source. Precedence: CLI > env > config/llm.json > `--config`
  > default. Both files contribute; one of them wins by some
  sub-rule.

**Decision**
**Option A.** When `--config <path>` is supplied, the resolver
chain treats that file as the config-file tier and skips
`config/llm.json` entirely for that run.

Implementation (in `_build_config`): if `args.config` is set,
load the file and inline the tier walk
(`args.provider or env_var or config.embedding_provider or
DEFAULT`). If not set, call the existing `resolve_*` helpers
(which read `config/llm.json` at tier 3).

**Why this over Option B**
- A user typing `--config experiment.json` is being explicit
  about reproducing a frozen experiment. Letting
  `config/llm.json` silently override the experiment defeats
  the purpose of pinning the config file at all.
- Option B's "stack and let one win" rule (whichever wins) is
  hard to predict from the call site. Option A is one rule:
  "file you point at replaces the project default."
- The user's stated rule is "CLI > env var > config json
  file under config/" — three tiers. Option A keeps three
  tiers from the user's perspective; Option B introduces a
  fourth.
- CLI flags + env vars still override `--config`, so the user
  can scope-narrow within an experiment without editing the
  pinned file.

**Consequences**
- New imports from `core.src.env.config` in
  `vectorstore_cli._build_config`:
  `DEFAULT_EMBEDDING_*`, `EMBEDDING_*_ENV_VAR`,
  `EMBEDDING_PROVIDERS`, `resolve_embedding_*`.
- Two pre-existing `test_env_config.py` bugs surfaced + fixed:
  `test_resolve_embedding_provider_precedence` and
  `test_resolve_embedding_model_precedence` previously
  assumed `config/llm.json` was empty (the project's prior
  state). Now monkey-patch `DEFAULT_LLM_CONFIG_PATH` to a tmp
  empty file. These tests were latent and only failed once
  the user populated `config/llm.json`.
- `_build_config`'s docstring now spells out the 4-tier
  resolution explicitly so future maintainers don't re-derive.
- Inverse-scenario verified live: with `config/llm.json`
  populated, no `--config`, no env var → resolver picks up
  qwen3-embedding:4b-q8_0. With `--config experiment.json`
  pinning bge-large → resolver picks up bge-large
  (config/llm.json is bypassed).
- The same pattern (Option A) is the likely answer for any
  future CLI that adds a `--config <path>` flag while
  participating in `config/llm.json`-driven defaults.

**Related**: D-044 (unified LLM/embedding config; this
extends D-044's resolution chain to a CLI that previously
didn't participate). The "back-compat to deprecated env-config
fields" tier from D-044 stays at the bottom and is unaffected.

---

## D-049: Stage 4.7 — hierarchy-based grouping with user-facing disambiguation

**Date**: 2026-05-06
**Status**: Accepted
**Phase**: Development

**Context**
After D-046 (chunk metadata `hierarchy_path`) and D-047 (relevance
threshold filter), retrieval still produced a failure mode: when a
query genuinely had multiple plausible answers in the corpus
(e.g. "What are the security requirements?" hits chunks under
multiple specs and multiple subsections), the LLM would synthesize
a single answer that conflated topics — picking somewhat arbitrarily
which chunks to lean on, and producing prose that read as
authoritative but was a low-confidence collapse of distinct
realities.

The user's stated principle, surfaced at the start of the
retrieval-improvements plan: *"the system shall not pretend it is an
Oracle."* When retrieval can't distinguish between plausible answer
groups, it should surface the choice rather than fabricate a synthesis.

**Decision**
New optional **Stage 4.7** in `QueryPipeline.query()`, between the
threshold filter (D-047, Stage 4.5) and context assembly (Stage 5):

1. Cluster post-threshold chunks by **greedy longest-common-prefix**
   on `hierarchy_path` metadata. Two chunks share a group iff they
   share at least the document root. Adjacent chunks in the
   alphabetically-sorted path order extend the running group's LCP.
2. **Group score** = `min(c.similarity_score for c in chunks)`. The
   best chunk anchors the group's relevance; weak siblings don't
   drag.
3. **Decision rule**: when `gap_between_top_groups(groups) >=
   gap_threshold`, **auto-commit** to the top group — its chunks
   alone go to Stage 5. When gap < threshold, return a
   `QueryResponse(disambiguation_required=True, groups=[…])` and
   skip Stages 5 and 6 (mirrors D-047's `_NOT_FOUND_ANSWER`
   short-circuit).
4. **Disambiguation UX**: the test page renders one Bootstrap card
   per group, each with the path breadcrumb, representative section
   titles, and a "Synthesize from this group" button. Click submits
   the picked group's chunk IDs to a new `pinned_chunk_ids` path
   that re-runs synthesis from those chunks only.
5. **Per-intent opt-out**: SUMMARIZE intent (D-051) is added to
   `_TYPE_DISABLE_GROUPING` because it inherently wants ALL groups
   merged into one synthesis — picking one defeats the purpose.

Three knobs in the unified resolver chain (D-050 / `config/retrieval.json`):

- `enable_grouping: bool` — global toggle. Default False (preserves
  pre-Step-3 behavior); flip to True to opt in.
- `gap_threshold: float` — distance gap below which disambiguation
  triggers. Default 0.05.
- `gap_threshold_by_type: dict[str, float]` — per-intent overrides.

**Why this over alternatives**
- *Pick the highest-scoring chunk and synthesize* — the pre-Step-3
  behavior. Loses the user's information-need signal whenever the
  top-K spans semantically-distinct groups; produces the
  "authoritative-looking but conflated" hallucination class.
- *Always return all groups; let the LLM merge* — rejected. The
  whole point of grouping is to let the user pick when the system
  can't. Always-merge would still pretend the system has one answer.
- *Cluster by k-means on the embeddings rather than by hierarchy* —
  rejected. Hierarchy is a structural signal the corpus authors
  provided; using it directly is more interpretable to users
  (path breadcrumbs are human-meaningful) and cheaper than running
  clustering at every query.
- *Group score = mean / max distance* — rejected for v1. min picks
  up "this group has at least one strong match"; mean dilutes when
  the group has weak siblings; max is dominated by the worst chunk.
  Empirically, min is the cleanest signal for "is this group
  relevant at all?"
- *Hard-fail / raise on ambiguity* — rejected. Disambiguation is a
  normal answer in the user workflow, not an error.

**Consequences**
- **Off by default.** `enable_grouping=False` preserves pre-Step-3
  behavior bit-for-bit; existing callers see no change.
- **Threshold is calibrated to the embedding model.** 0.05 default
  came from in-session tuning on env_vzw + qwen3-embedding:4b-q8_0.
  Different models will need different defaults — the per-type
  override map is the migration path.
- **New `QueryResponse` fields**: `disambiguation_required: bool`
  and `groups: list[ChunkGroup]`. Old API consumers that ignore
  unknown fields are unaffected; new consumers need to check the
  flag before assuming `answer` is a real synthesis.
- **New `pinned_chunk_ids` parameter on `QueryPipeline.query()`** —
  bypasses Stages 2-4.7 (resolver / graph scope / rewrite / RAG /
  threshold / grouping) and goes straight to synthesis. Powers the
  card-click flow; also a useful primitive for "synthesize from a
  hand-picked set" use cases.
- **New module `core/src/query/grouping.py`** with
  `group_chunks_by_hierarchy()` and `gap_between_top_groups()`.
  Singletons, multi-doc clusters, and back-compat (chunks with
  empty `hierarchy_path`) all handled.
- **Web layer adds a new endpoint** (`POST /api/test/synthesize-group`)
  + Bootstrap card rendering in `_answer.html`.
- **38 new tests** across grouping logic + pipeline integration +
  pinned-chunks path + cap interaction.

**Related**: D-046 (chunk metadata hierarchy_path; the input
grouping reads), D-047 (threshold filter; runs before grouping),
D-050 (Phase 3-config infrastructure; the knobs ride on it),
D-051 (FACT/SUMMARIZE intents; SUMMARIZE opts out of grouping),
D-052 (citation audit; runs after this stage).

---

## D-050: Phase 3-config — `config/retrieval.json` extends the unified resolver chain

**Date**: 2026-05-06
**Status**: Accepted
**Phase**: Development

**Context**
Stage 4.7 (D-049) introduced two new tunable knobs (`enable_grouping`,
`gap_threshold`) plus a per-type override map. The user's request
when Step 3 was scoped: *"all tunable parameters [shall] be
configurable through the standard 3-tier config architecture (CLI
> env > config-file > default)."*

Existing retrieval tunables (`_TYPE_TOP_K`, `_TYPE_BM25_WEIGHT`,
`_TYPE_RERANK_ENABLED`, `_TYPE_REWRITE_ENABLED`) lived as
hand-edited dicts in `core/src/query/pipeline.py` — not configurable
without code changes. The decision: do we (a) migrate everything in
one big refactor, or (b) seed new infrastructure for the Step 3
knobs and migrate existing knobs incrementally?

**Decision**
Phased approach. **Phase 3-config (this commit)** adds the
infrastructure — a new file, dataclass, and resolver helpers — but
wires only the Step 3 knobs through it. **Phase 4-migrate (next
session, separate scope)** migrates the existing per-type dicts
into the same file with backward-compatible defaults. Each migrated
knob is its own atomic commit.

Concretely:

- New `config/retrieval.json` parallel to `config/llm.json`
  (D-044). Schema seeded with `enable_grouping`, `gap_threshold`,
  `gap_threshold_by_type`. Comment in the file documents Phase
  4-migrate's planned additions.
- New `RetrievalConfig` dataclass in `core/src/env/config.py`
  mirrors `LLMConfigFile`'s shape (cached via
  `_retrieval_config()`, test hook `_reset_retrieval_config_cache()`).
- Two new resolver helpers `resolve_grouping_enabled` /
  `resolve_gap_threshold` follow the D-044 chain: CLI > env var >
  config file > default. The threshold helper additionally honors a
  per-type override (`gap_threshold_by_type[query_type]`) above the
  scalar default in the file.
- New env vars `NORA_RETRIEVAL_GROUPING_ENABLED` /
  `NORA_RETRIEVAL_GAP_THRESHOLD`. Naming convention is
  `NORA_RETRIEVAL_<KNOB>` for everything in `config/retrieval.json`,
  parallel to D-044's `NORA_LLM_*` / `NORA_EMBEDDING_*`.
- **Per-type maps are file-only.** No env var or CLI flag for them
  — JSON-typed and rarely need shell-level override.

**Why this over alternatives**
- *Migrate all retrieval knobs at once* — rejected. Each knob needs
  its own resolver, env var, CLI flag, doc update, and test;
  bundling would produce a 6-hour commit chain blocking Step 3
  shipping. Phased migration keeps each piece reviewable.
- *Drop the per-type dicts and only have file-driven config* —
  rejected. The dicts encode empirical tuning rationale (comments
  explain why each value); preserving them as built-in defaults
  the file overrides keeps that institutional knowledge visible.
- *One mega config file (`config/all.json`)* — rejected. The D-044
  separation (`config/llm.json` for LLM/embedding,
  `config/retrieval.json` for retrieval, `config/web.json` for web
  serving, `config/env.json` for DB paths) keeps unrelated lifecycles
  separate.
- *Env vars for everything (no JSON file)* — rejected for the same
  reason D-044 rejected it: too many knobs make for messy shell
  prompts.

**Consequences**
- **One new tracked file** `config/retrieval.json` ships with empty
  defaults so fresh clones are unaffected.
- **Pattern set for Phase 4-migrate**: each knob gets a `resolve_*`
  helper, optional env var, dataclass field, test isolation pattern
  (monkey-patch `DEFAULT_RETRIEVAL_CONFIG_PATH` to a tmp file).
- **Two pre-existing test bugs surfaced** when extending the
  resolver test patterns to `RetrievalConfig`:
  `test_resolve_embedding_provider_precedence` and
  `test_resolve_embedding_model_precedence` weren't isolating from
  `config/llm.json` on disk. Fixed alongside this commit.
- **9 new resolver tests + 22 grouping tests** pin the precedence
  chain end-to-end.
- **D-053 (Config-page DB layer) builds on this**: when the DB
  hydrates the cached `RetrievalConfig` instance at startup, the
  existing resolvers automatically pick up the DB layer with no
  code changes — no ad-hoc plumbing needed for new knobs.

**Related**: D-044 (unified LLM config; this is the same pattern
extended), D-049 (Stage 4.7; the first set of knobs to ride on this
infrastructure), D-053 (Config-page DB layer; slots into the same
chain).

---

## D-051: FACT and SUMMARIZE intent classification — query-shape vs query-intent

**Date**: 2026-05-06
**Status**: Accepted
**Phase**: Development

**Context**
The existing `QueryType` values (SINGLE_DOC, CROSS_DOC,
CROSS_MNO_COMPARISON, RELEASE_DIFF, STANDARDS_COMPARISON,
TRACEABILITY, FEATURE_LEVEL, GENERAL) classified queries by their
**scope shape** — how many documents / specs / MNOs the answer
spans. The pipeline used the type to drive `top_k` widening, BM25
weighting, rerank toggling, etc.

But shape isn't intent. "Explain authentication requirements"
classified as SINGLE_DOC or GENERAL (no breadth triggers in the
phrasing) — and got `top_k=10` plus Stage 4.7 grouping that picked
the deepest LTEOTADM AUTHENTICATION subsection, returning 3 chunks
when the user wanted a survey across all the auth-related content
in the corpus. Conversely, "What is the value of T3402?" needed
*precision* (tight top_k, strict threshold, contradiction surfacing)
that none of the shape-types encoded.

The user's contribution: *"add 'Fact' intent — high similarity in
all fragments, per-sentence attribution, contradiction detection
mandatory"* and *"add 'Summarize' intent — structural navigation,
TL;DR first, per-group summaries"*.

**Decision**
Two new `QueryType` values, classified by phrasing:

- **`QueryType.SUMMARIZE`** — survey/summarize intent. Triggers:
  `explain `, `summarize`, `summary of`, `describe `, `give me an
  overview`, `overview of`, `tell me about `. Per-intent knobs:
  `top_k=50` (wide), `bm25_weight=0.2` (mostly dense — user
  paraphrases the topic), `rerank_enabled=False` (cost vs benefit
  at top-50; LLM reads everything anyway), `rewrite_enabled=True`
  (term expansion gathers more), `max_distance_threshold=0.7`
  (lenient — wants breadth including parent/overview chunks),
  `_TYPE_DISABLE_GROUPING={SUMMARIZE}` (skip Stage 4.7 entirely —
  auto-commit to one group throws away the breadth the user wants).
  System prompt: *"Structure your answer in two parts: TL;DR + per-
  section breakdown."*

- **`QueryType.FACT`** — fact-lookup intent. Triggers: `value of`,
  `what value`, `default value`, `default for`, `how many`,
  `how long`, `maximum value`, `minimum value`, `exact value`,
  `specific value`, `what is the limit`, `what is the threshold`.
  Per-intent knobs: `top_k=10` (tight; 1-3 chunks usually carry the
  fact), `bm25_weight=0.5` (term-match for specific tokens),
  `rerank_enabled=True` (precision matters), `rewrite_enabled`
  intentionally absent — default False, because paraphrasing a
  fact-shaped query risks substituting it into a definitional query
  (D-043 acronym path is wrong for "what's the *value*"),
  `max_distance_threshold=0.4` (strict — fact-shaped answers from
  weak chunks are the worst-case hallucination), grouping enabled
  (one fact = one group typically). System prompt: *"Direct answer
  + per-sentence attribution; contradiction handling: surface
  disagreement explicitly when sources differ."*

**Classification priority**: FACT is checked *before* SUMMARIZE in
`_classify_query_type` so "Explain the value of T3402" routes to
FACT (precision) not SUMMARIZE (breadth) when both phrasings
appear. Bare "what is X" stays out of FACT — it's definitional
(D-043 acronym pin) or falls through.

**Why this over alternatives**
- *Add a separate `Intent` enum orthogonal to `QueryType`* —
  considered. Cleaner conceptually (shape and intent are different
  axes) but doubles the routing matrix and requires every per-type
  dict to become a 2-D map. Deferred — single-axis enum works
  while we have only two intent values; revisit if more intents
  land.
- *LLM-driven classification (use `LLMQueryAnalyzer` for FACT/SUMMARIZE
  detection)* — rejected for v1. Phrase triggers are deterministic,
  fast, and explainable; an LLM call adds latency and a failure mode.
  The trigger list can grow as miss cases surface.
- *Add Comparison intent now* — explicitly **deferred**. User asked
  to skip until multi-MNO / multi-release ingestion lands; no test
  data to validate against today.
- *Make breadth-trigger phrases SUMMARIZE instead of CROSS_DOC* —
  rejected. CROSS_DOC ("what are all the X requirements") is a
  *scope* signal — "show every relevant requirement, structured by
  doc". SUMMARIZE is an *output-shape* signal — "produce a TL;DR +
  breakdown." A query can be both (cross-doc summarize); the
  routing currently picks the more-specific intent (SUMMARIZE wins
  when phrased explicitly).

**Consequences**
- **Per-type dicts grew** (`_TYPE_TOP_K`, `_TYPE_BM25_WEIGHT`,
  `_TYPE_RERANK_ENABLED`, `_TYPE_REWRITE_ENABLED`,
  `_TYPE_MAX_DISTANCE`); new `_TYPE_DISABLE_GROUPING` set. Phase
  4-migrate (D-050) will move these into `config/retrieval.json`.
- **Stage 4.7 honors per-intent grouping opt-out** — pipeline checks
  `intent.query_type not in _TYPE_DISABLE_GROUPING` before clustering.
- **Two new `_SYSTEM_PROMPTS` entries** in `context_builder.py`
  with TL;DR-vs-fact framing.
- **29 new tests** pin classification (5 SUMMARIZE phrasings, 6 FACT
  phrasings, classification priority FACT-beats-SUMMARIZE), per-
  intent knob assertions, system-prompt content assertions, and
  Stage 4.7 bypass for SUMMARIZE.
- **`/v1` of contradiction detection is prompt-only.** The FACT
  prompt asks the LLM to surface disagreements; deterministic
  semantic-comparison detection across chunks is left for a future
  step.
- **Comparison intent still deferred** — flagged in STATUS.md
  Next; revisit when second MNO corpus ingests.

**Related**: D-039 (entity-priority graph scoping; FACT queries that
name a specific req still hit this path), D-040 (per-type top_k +
list-style detection; this extends the same shape into intent
routing), D-043 (acronym pin; bare "what is X" stays in this path,
not FACT), D-049 (Stage 4.7; SUMMARIZE opts out via
`_TYPE_DISABLE_GROUPING`).

---

## D-052: Stage 6.5 — per-sentence citation audit

**Date**: 2026-05-06
**Status**: Accepted
**Phase**: Development

**Context**
Synthesis prompts demand inline citations (D-001 invariant: every
factual claim must reference a `(VZ_REQ_X)` or 3GPP TS section).
The synthesizer already extracts citations the LLM mentioned and
back-fills missing ones from context. But two error classes still
slipped through unnoticed:

1. **Uncited factual claims** — sentences in the answer that don't
   cite anything. May be paraphrasing correctly across multiple
   reqs, may be hallucinating; the user has no way to tell.
2. **Fabricated citations** — req IDs in the answer that don't
   appear in the chunks the LLM actually received. Worst-case error
   class — looks authoritative, isn't real. Surfaced in the
   user's session via "What is SDM?" hallucinating "SIMOTA Device
   Management" before D-043 fixed the retrieval-side path; same
   phenomenon for any topic where retrieval misses and the LLM
   invents.

The user's stated principle from Step 5 scoping: *"per-sentence
citation polish layer."*

**Decision**
New **Stage 6.5** runs after synthesis on the normal path:
`audit_answer_citations(response.answer, available_req_ids)` walks
the answer sentence-by-sentence and produces a `CitationAudit`:

- **Sentence splitter** is regex-based with abbreviation handling
  (e.g., i.e., etc., ...), markdown-header detection, and bullet/
  numbered-list awareness. Each list item is its own sentence;
  headers are marked `is_meta=True` and excluded from the cited-
  percentage metric.
- **Citation detector** matches the same regex patterns the
  synthesizer's `_extract_citations` uses (`VZ_REQ_X` and
  `3GPP TS Y, Section Z`). A sentence is considered cited if it
  contains either form.
- **Fabrication detector** flags req IDs in the answer that are
  NOT in `available_req_ids` (the chunks passed to the LLM). 3GPP
  spec citations are external and always pass.
- **`CitationAudit` schema dataclass** carries per-sentence audits
  + summary counts (`cited_sentence_count`, `factual_sentence_count`,
  `fabricated_count`, `cited_percent` property,
  `uncited_sentences` property).

`QueryResponse.citation_audit: CitationAudit | None` — populated on
the normal synthesis path AND the pinned-chunks path; None on
disambiguation/not-found paths (no real answer to audit).

Web layer surfaces the audit in `_answer.html`:
- Inline summary `4/6 sentences cited (66.7%) · 1 fabricated`.
- Collapsible "show uncited" list with yellow border per sentence.
- Red alert banner when fabricated citations exist, listing the
  bad req IDs and the sentence containing them.

**Why this over alternatives**
- *LLM-judged audit (second LLM call to grade the answer)* —
  rejected. Adds latency and another failure mode; deterministic
  regex sufficient for "is there a citation token?" — that's the
  bar.
- *Re-prompt the LLM to fix uncited sentences (Phase 5c)* —
  **deferred**. Costly (a second LLM call per query) and unclear if
  the retry would do better. Real-world miss rates need measuring
  first; revisit after a few weeks of usage data.
- *Strict-mode synthesis (refuse to render any uncited sentence)* —
  rejected. Prose flow needs transition sentences ("The X timer
  governs the procedure.") that don't cleanly attach to one req.
  Too aggressive; would force unnatural phrasing or many false
  positives.
- *Inline highlight of uncited spans in the rendered answer* —
  considered, but rendering deletes the sentence boundaries our
  audit operates on. Showing the audit as a collapsible side-list
  is simpler and doesn't fight the markdown renderer.

**Consequences**
- **Always-on, no LLM call.** Adds < 1ms to every synthesized
  query; a regex pass over a few thousand chars.
- **Two new schema dataclasses** on `QueryResponse.citation_audit`:
  `SentenceAudit` (per-sentence) and `CitationAudit` (summary).
  Old API consumers see new field they can ignore.
- **New module `core/src/query/citation_audit.py`** with the
  splitter + detector. Tested against realistic SUMMARIZE-style
  (TL;DR + bullets) and FACT-style (with contradictions) outputs.
- **Surfaces a metric per query**: `cited_percent`. Lets us see
  "is the LLM following the citation prompt?" objectively. Below
  ~80% suggests prompt-strength issue or weak model.
- **27 new tests** cover sentence splitting (single/multi/abbreviation/
  paragraph/bullet/numbered/header), markdown header detection,
  audit basics, fabrication detection, meta-sentence handling,
  uncited accessor, two realistic answer styles.
- **Phase 5c citation repair (re-prompt) deferred** to STATUS.md
  Next.

**Related**: D-001 (citation invariant; this is the audit layer
that makes it observable), D-043 (acronym pin; preventing the
retrieval-side root cause that this audit catches at the synthesis
side), D-049 (Stage 4.7 disambiguation; runs before this audit on
synthesis path), D-051 (FACT prompt asks for per-sentence attribution
explicitly; audit measures whether the LLM complied).

---

## D-053: Config-page DB layer slots between env vars and JSON files

**Date**: 2026-05-06
**Status**: Accepted
**Phase**: Development

**Context**
Through this session, the user repeatedly asked "did my config
change actually take effect?" — first when wiring a custom Ollama
proxy, then after switching embedding models, then when setting
top_k=25 and getting 50 chunks. Each time required either grepping
the server log for resolved values or running ad-hoc CLI tools.
The signal was clear: **admins want a UI for the config knobs, with
visible verification.**

The user's request that triggered the Config page implementation:
*"all configurable params (that are under config/) can be updated by
the user. All the updated values go into a config db ... user
provides full path from command line or env variable. ... If user
changes some config values, they shall be written to db, and then
rest of web app shall reflect the new values."*

The architectural question: **where does the DB sit in the resolver
chain?** Three plausible options.

**Decision**
The DB layer slots **between env vars and `config/*.json`**:

```
CLI flag > env var > ConfigStore (this DB) > config/*.json > defaults
```

The DB is a **persistent layer for user-edited overrides via the
web UI**. Higher than the JSON files because the user explicitly
set it through the page (more recent, more specific intent).
Lower than env vars because env vars remain the admin's hard-override
escape hatch ("set this for the next 5 minutes without touching the
DB").

Implementation:

- New `core/src/web/config_db.py` — synchronous SQLite-backed
  `ConfigStore` keyed by `(module, key)`. Values JSON-encoded so
  int / bool / float / list round-trip cleanly. Threadsafe via
  internal lock.
- New `core/src/web/config_schema.py` — hand-curated
  `CONFIG_SECTIONS` describing the 13 user-editable knobs (LLM and
  Retrieval sections; categories `feature` / `value` / `tunable`;
  kinds `bool` / `string` / `int` / `float` / `enum` / `password`).
  Drives the form rendering.
- **`apply_to_caches()` at app startup**: overlays every stored
  value onto the cached `LLMConfigFile` / `RetrievalConfig`
  instances. The existing `resolve_*` functions in
  `core/src/env/config.py` automatically pick up the DB layer
  with no plumbing changes — they were already reading from the
  cached instances, so mutating those instances after JSON load
  effectively inserts the DB tier into the chain.
- **`reapply_one()` after each save**: cheaper than a full re-apply
  when the UI edits one field. Pipeline cache (`app.state.query_pipeline`)
  is also invalidated on each save so the next query rebuilds.
- **Opt-in**: new CLI `--config-db` + env var `NORA_CONFIG_DB`. If
  unset, the page renders read-only with a notice; the resolver
  chain falls through as before. No default path, deliberate —
  the user must opt in.

**Why this over alternatives**
- *DB **above** env vars (DB always wins)* — rejected. Env vars
  are the admin's debug / emergency-override channel; making them
  losable to a stale DB row would be a footgun. Order preserves
  the principle that the most-specific, most-recent override
  wins (CLI flag = "I just typed this" beats env var = "this shell
  has it set" beats DB = "I saved this earlier" beats file =
  "this is the project default").
- *DB **below** the JSON files (file always wins)* — rejected.
  Defeats the purpose of the editor — saving a value through the
  UI would no-op if the JSON file had a different value. The DB
  must override the file for "user edited this through the UI" to
  mean anything.
- *Replace JSON files entirely with the DB* — rejected. JSON files
  are project-checked-in defaults; team members pulling main
  inherit them. Deleting that layer would force everyone to also
  set up a DB, breaking the "fresh clone works" property.
- *Modify `resolve_*` functions to read from the DB directly* —
  rejected. Would require a registry of "which DB connection are
  we in?" plumbed everywhere. The chosen approach (overlay onto
  the existing dataclass cache) is dramatically simpler and
  reuses the resolver chain unchanged.
- *Always-default DB at `<env_dir>/state/config.db`* — considered
  but rejected. Some users won't want persistence at all (CI runs,
  ephemeral test environments); explicit opt-in is cleaner than
  always-creating a DB no one asked for.

**Consequences**
- **One new SQLite file per env that opts in**, ~8 KB schema-only.
  Grows by ~100 B per saved value.
- **New `app.state.config_store`** — None when DB disabled (read-
  only Config page); ConfigStore instance when enabled. Other
  routes can also read from it (e.g. `routes/query.py` reads
  `pipeline.top_k_cap` and `pipeline.max_distance_threshold` for
  knobs that don't have a cached dataclass slot).
- **`apply_to_caches()` runs once at app startup**, before any
  request lands. The first query naturally builds its pipeline
  with the DB-overlaid cache state.
- **Save invalidates the cached pipeline.** Next query rebuilds
  with the new resolved values. The startup-log lines (`Web LLM
  resolved: …`, `Top-K cap: …`, `Stage 4.7 grouping: …`) print
  again on first query, so admins can see what landed.
- **Two pre-existing build-time-only knobs are now settable but
  misleading**: `embedding_provider` / `embedding_model` (pinned
  at vectorstore-build time per `<env_dir>/out/vectorstore/config.json`
  and consumed by the web app from there, not the LLMConfigFile);
  `skip_taxonomy` / `skip_graph` (pipeline-runner stage toggles,
  not query-time). Saving them populates the DB and overlays the
  caches but query behavior won't change without a vectorstore
  rebuild. Flagged in STATUS.md to either move to a "Pipeline
  (rebuild required)" section with caveat help text or drop.
- **DB-key change `top_k` → `top_k_cap`** in c2dff4f (one commit
  after the Config page shipped) — old DB rows are silently ignored
  by the new resolver. No migration shipped because the field had
  only existed for one commit.
- **25 new tests** cover ConfigStore CRUD (string/bool/int/float
  round-trips, missing-key, upsert, get_module, get_all, delete,
  cross-instance persistence), `apply_to_caches` overlay, schema
  integrity, and end-to-end route smoke (GET /config renders both
  modes; POST persists).

**Related**: D-022 (per-env runtime directory; the DB lives at
`<env_dir>/state/config.db` by convention even though no default
is enforced), D-044 (unified LLM config; the chain this layer
extends), D-050 (Phase 3-config infrastructure;
`config/retrieval.json` is one of the JSON files this layer sits
above).

---

## D-054: Cline scaffold for on-prem teacher/student collaboration

**Date**: 2026-05-07
**Status**: Accepted
**Phase**: Development

**Context**
NORA processes proprietary US-MNO requirement documents that cannot
leave the on-prem network. Two debug-loop pain points emerged this
work-week:

1. The user couldn't show me corpus content (no copy-paste between
   on-prem and cloud machines) so I was designing parser rules and
   profile schemas blind, relying on the user to manually translate
   observations into compact reports each iteration. Slow and
   error-prone.
2. Existing on-prem AI partners (Cline) could see the corpus and
   were perfectly capable of running NORA's CLIs, profiling docs,
   running pipelines — but had no structured contract telling them
   what their role was vs the Teacher LLM's, what to leak vs not,
   and how to format outputs so the user could hand-type them
   into the Teacher LLM chat.

The user proposed: split responsibilities. On-prem AI (Cline) sees
the corpus, profiles, debugs, and produces compact redacted
reports. The Teacher LLM (intentionally generic — the
scaffold doesn't name a vendor) sees the full repo, designs and
codes. Code transfers via git; observations transfer via hand-typed
reports. Per-project scaffolding tells Cline what to do.

**Decision**
14-file scaffold under the NORA repo, structured as:

- **`.clinerules/` (always-on, ~7KB total)** — Cline's rule engine
  auto-loads everything in this directory:
  - `00-project.md` — what NORA is, where to read more
  - `01-role.md` — Cline as on-prem student, the cloud "Teacher LLM"
    as teacher, the standard loop diagram (playbook → redacted
    report → hand-typed → code via git → re-test)
  - `02-content-safety.md` — full redaction protocol with literal-
    string mapping at `<env_dir>/state/cline-mapping.json` (on-prem
    only; placeholders `<MNO{N}>` / `<PLAN{N}>` / `<REQID-{N}>`);
    forward redaction for outgoing reports, reverse substitution
    for incoming Teacher LLM responses; hard rules for what never
    leaves on-prem (verbatim prose, file paths under `<env_dir>/input/`,
    requirement-body content, table cell data)
  - `03-output-discipline.md` — hand-typeable reports (≤30 lines
    max), tabular over prose, fixed format per playbook, six
    standard report types (ORIENT / MAP / PROF / RULE / RPT /
    BUNDLE)
- **`cline-playbooks/` (invokable manually)** — 6 initial
  playbooks (orient / mapping / profile-corpus / debug-pipeline
  / derive-rule / share-back) + 3 bootstrap-related additions
  (annotation-schema / bootstrap / feedback-loop, captured
  separately as D-055).

Workflow loop:
```
   ┌── on-prem (Cline + corpus) ──┐               ┌── cloud (Teacher LLM) ──┐
   │  1. invoke playbook          │   manual      │  3. read report         │
   │  2. produce compact report   │   typing      │  4. design + code       │
   │  6. git pull                 │ ◀── git ────  │  5. commit              │
   │  7. run new code             │               │                         │
   │  8. produce next report      │ ───────────▶  │  9. respond             │
   └──────────────────────────────┘               └─────────────────────────┘
```

Steps 3 + 9 are user-typed manually. Code never moves through chat —
only through git.

**Why this over alternatives**
- *Everything in `.clinerules/` (single concatenated rules file)* —
  rejected. Cline concatenates every file in the directory into one
  always-on prompt; bundling 7 playbooks + 4 always-on rules would
  bloat every Cline interaction with playbook content not relevant
  to that conversation. Splitting playbooks into a manually-invoked
  directory keeps the always-on budget tight.
- *Have Cline write code under `core/src/`* — rejected. Two reasons:
  (a) Teacher LLM has the full design context; Cline doesn't need
  to and shouldn't second-guess architecture decisions; (b) bounding
  Cline's authority makes review easier — the user only reviews
  reports going out and Teacher LLM's commits going in, never an
  in-place Cline-edited core source file.
- *Generic "AI assistant" naming* — rejected (initially used "Claude"
  per the LLM provider in use at the time, but corrected per user
  preference to "Teacher LLM"). The vendor-neutral naming makes the
  scaffold portable (different team members may use different Teacher
  LLMs; the scaffold doesn't care).
- *Copy-paste between machines* — rejected by physics: the user's
  on-prem and cloud machines are air-gapped (no shared clipboard).
  Hand-typing budget drives every report to ≤30 lines, tabular,
  numerical-not-prose. Code transfer goes through git.
- *Always-default redaction mapping at `<env_dir>/state/`* —
  considered. Decided **opt-in** with an explicit `<env_dir>/state/
  cline-mapping.json` path. The mapping never enters git (env_dir
  is gitignored). Cline allocates new placeholders on demand;
  the user reviews periodically.

**Consequences**
- **Scaffold lives in NORA repo for v1.** When a second project
  with on-prem corpus needs the same pattern, lift to a portable
  `compact-cline-template/` (analogous to the COMPACT scaffold for
  Teacher LLM, which is the user-global `.claude/skills/`
  scaffold). For v1, NORA-specific paths/CLIs are hardcoded —
  faster to validate the design, cleaner to template after.
- **New on-prem-only file** at `<env_dir>/state/cline-mapping.json`.
  Per-env, never in git. Schema covers MNO short / MNO alias / MNO
  full name / Plan ID / Plan name / Release / Req ID. Stable
  indexes per category — once allocated, never changes. Cline
  emits a `MAPPING:` line inline whenever it allocates a new entry.
- **Hand-typing budget is the tightest constraint.** Every report
  type has a hard line limit. PROF ≤15. RULE ≤10. RPT ≤25. BUNDLE
  ≤40. Without these caps, the workflow doesn't scale.
- **Validation gap surfaced and tracked**: the loop is end-to-end
  unproven on a real corpus until the user runs orient → mapping →
  profile-corpus on a work-PC doc and reports back. Flagged in
  STATUS.md.
- **Annotation web UI for PDF/DOCX/XLSX deferred** as a separate
  Teacher-LLM task. Schema doesn't change when the UI lands;
  hand-typed JSON works in the interim.

**Related**: D-008 (web UI for non-CLI team members; the Cline
scaffold partners with that channel — Cline reads Parse Review
output, web UI hosts the human-review side), D-022 (per-env
runtime directory — the redaction mapping is one more file under
`<env_dir>/state/`), D-055 (bootstrap → feedback-loop pattern;
the Day-0 / Day-N rule-derivation flow that rides on this
scaffold). The scaffold itself is independent of any specific
ADR — D-054 stands alone as "how on-prem (Cline) and the Teacher LLM
collaborate in this project" and D-055 is the rule-derivation
pattern that runs on top of it.

---

## D-055: Bootstrap → feedback-loop pattern for human-in-the-loop rule derivation

**Date**: 2026-05-08
**Status**: Accepted
**Phase**: Development

**Context**
The cline scaffold (D-054) lets Cline derive parser/profile rules
from on-prem corpus content, but the v1 derivation path
(`derive-rule.md`) had Cline sample the corpus itself (10 instances
+ 10 NEAR-misses per element) and infer rules from those. That's
brittle: Cline's choice of "instances" can be unrepresentative;
self-reported coverage stats can be wrong because Cline scores its
own rule.

The user proposed a more grounded loop:

1. **Day 0** — humans annotate 3-5 corpus files marking regions of
   each kind (TOC / section_heading / strikethrough / etc).
   Annotations capture location + kind, not verbatim content.
2. **Day 0** — Cline reads the annotations, derives rules from
   the human-marked regions, emits a compact BOOTSTRAP report.
3. **Day 0** — Teacher LLM commits initial profile + parser code.
4. **Day N** — humans review parser output via the existing Parse
   Review web page, mark wrong rows / missed rows.
5. **Day N** — Cline reads the review-derived corrections (CSV from
   the web page) and emits a FEEDBACK report categorizing failure
   modes and proposing rule refinements.
6. **Day N** — Teacher LLM commits the refinement + an integration
   test that pins the failure mode it just fixed.
7. Loop steps 4-6 until coverage stabilizes.

**Decision**
Three new files in `cline-playbooks/`:

- **`annotation-schema.md`** (reference, ~225 lines) — JSON sidecar
  format per source doc at `<env_dir>/annotations/<plan>_annotations.json`.
  Supports 9 kinds: `section_heading`, `req_id`, `toc`,
  `strikethrough`, `version_history`, `definitions`, `applicability`,
  `priority`, `references` (with `intra_doc` / `cross_doc` / `spec`
  subkinds). Region format per doc-type: PDF (page+bbox or
  line_range), DOCX (paragraph indices or table+row), XLSX (sheet+rows).
  **Positive examples only** — false positives caught later by the
  feedback loop, not by negative annotations.
- **`bootstrap.md`** (invokable, ~120 lines) — reads annotations,
  groups by kind across docs, derives one rule per kind, emits
  BOOTSTRAP report (≤25 lines, one line per kind with regex/heuristic
  + sigma=annotation-count + TP).
- **`feedback-loop.md`** (invokable, ~110 lines) — reads
  `<env_dir>/reports/audit/<plan>_audit.csv` and per-req correction
  overrides, categorizes FPs/FNs by structural failure mode (max 3
  per kind), proposes rule refinement, emits FEEDBACK report (≤20
  lines, ≤3 kinds per report — split into multiple reports if more).

`derive-rule.md` (the pre-existing fallback playbook) is now
explicitly the **fallback** — for cases where annotations don't
exist yet AND the parser hasn't run yet. The README's
decision-diagram routes humans to bootstrap → feedback-loop when
annotations are available.

**Why this over alternatives**
- *Negative annotations (mark "this is NOT a TOC")* — rejected for
  v1. User feedback: "Difficult to provide negative examples for
  bootstrap annotations. However, human feedback later on actual
  parse output will catch FPs." Accept the FN-only signal at
  bootstrap; let the feedback loop catch FP rate after the parser
  has run on the full corpus.
- *Cline writes profiles directly* — rejected. Per D-054 invariant
  ("Cline doesn't write code under `core/src/`"). Cline emits the
  BOOTSTRAP/FEEDBACK reports; Teacher LLM commits the profile.json
  changes and any parser code. Stricter separation = easier review.
- *Annotation web UI for v1* — deferred. User selected option (b)
  ("Annotate page in NORA web UI") for the long term, but
  acknowledged the substantial scope (PDF.js for PDFs, IR-rendering
  for DOCX/XLSX). For v1, hand-typed JSON sidecars validate the
  schema and the loop end-to-end. Schema doesn't change when the
  UI lands.
- *Cline emits one report per kind* — rejected for bootstrap (one
  combined BOOTSTRAP report covering all annotated kinds is more
  efficient for the user's typing trip). Kept per-kind in feedback-
  loop because feedback usually focuses on 1-3 kinds at a time and
  per-kind detail helps Teacher LLM make targeted fixes.

**Consequences**
- **New on-prem-only directory** `<env_dir>/annotations/` for
  hand-typed JSON until the web UI lands. Per the ban on `<env_dir>`
  in git (D-022), these never enter the repo.
- **Reference subkinds become first-class.** The `references` kind
  with `intra_doc` / `cross_doc` / `spec` subkinds means the parser
  may need new code for cross-doc reference resolution and 3GPP
  spec citation handling. NORA's parser already has some of this
  (the resolve stage handles intra-doc + cross-doc xrefs); spec
  citations are partially captured but not as a first-class
  annotation kind. When the user runs bootstrap on a corpus and the
  BOOTSTRAP report names `references` as a kind to add coverage
  for, that becomes a Teacher-LLM commit.
- **Three new playbook files** — schema (reference), bootstrap
  (invokable), feedback-loop (invokable). `derive-rule.md` updated
  with a front-pointer noting the preferred path.
- **Bootstrap is positive-only** — accept that bootstrap rule rates
  are TP/sigma, not TP/FP/FN. The feedback loop is where FP rates
  get measured (against real parser output reviewed by humans).
- **Loop convergence is unproven on a real corpus.** Flagged in
  STATUS.md as "validate the cline scaffold end-to-end on the work
  PC" — orient → mapping → profile-corpus → bootstrap → run
  pipeline → feedback-loop. Iterate playbook formats based on what
  the work PC produces.
- **Annotations cap is empirical**: 3-5 docs, 5-10 examples per
  kind per doc. Smaller → low-confidence rule (BOOTSTRAP report
  flags `LOW_PROV: <kind>` when sigma < 3). Larger → tedious for
  the human. Tunable per project.

**Related**: D-008 (web UI for non-CLI team members; Parse Review
page is the feedback-loop input channel), D-027 (parser table-
anchored requirements; this loop is how new corpus types validate
that parser change generalizes), D-054 (cline scaffold; this is the
rule-derivation pattern that runs on top of it), D-038 (table-
anchored definitions extraction; same shape — corpus-derived rule
that could have come through bootstrap had the loop existed). The
loop is corpus-agnostic and stage-agnostic but currently exercised
mostly on `parse` and `profile`; could extend to `resolve` and
`eval` per the playbook table in `feedback-loop.md`.

---

## D-056: Build the annotation harness in NORA before exercising the Cline scaffold
**Status**: Active · **Date**: 2026-05-08
**Decision**: Ship a web-UI annotation editor (Bootstrap tab on the Parse page) that writes `<env_dir>/annotations/<plan>_annotations.json` per `cline-playbooks/annotation-schema.md`, before inviting the user to run Cline's `bootstrap.md` for the first time.
**Why**: Annotation quality is the bottleneck on whether bootstrap-derived rules generalize; hand-typing JSON for 3-5 docs × 5-10 examples × 9 kinds is tedious and typo-prone, gating every new corpus onboarding. Vs ad-hoc CLI: doesn't let the human visually align selections against IR + DOCX preview. Vs deferring to "after first dry run": the dry run depends on the artifact this UI produces, so deferring just postpones the same work.
**Consequences**: NORA web UI surface grows with one more page-tab. The DOCX renderer's index-alignment with `DOCXExtractor` becomes a load-bearing invariant (D-057). Annotation file format is now a contract between the UI and Cline's `bootstrap.md`; schema changes touch both. PDF/XLSX UIs still deferred; humans handwrite JSON for those formats until the next non-DOCX corpus arrives.

---

## D-057: Custom DOCX-to-HTML walker, index-aligned with DOCXExtractor
**Status**: Active · **Date**: 2026-05-08
**Decision**: `core/src/web/docx_html_render.py` walks `doc.element.body.iterchildren()` in the same order as `DOCXExtractor.extract` and applies the same skip rules (empty paragraphs return None; degenerate single-empty-column tables dropped). Every emitted HTML element carries `data-block-idx="N"` matching `ContentBlock.position.index`.
**Why**: The IR's flat block index is what annotations reference and what Cline's `bootstrap.md` consumes — the renderer must match it. Vs mammoth: doesn't know about IR alignment, would require a separate post-pass to drop empty `<p></p>` and re-number, which is exactly the custom walker minus the dependency. Vs pypandoc: requires the pandoc binary, breaking the offline-install path. Vs no preview (IR-only): user explicitly chose side-by-side because IR-only loses too much context for hand-annotation.
**Consequences**: Any change to `DOCXExtractor`'s iteration order or skip rules MUST mirror in `docx_html_render.py` or every saved annotation drifts on next render. Invariant added to `web/MODULE.md`. Test fixture (`test_parse_bootstrap.py::TestDocxRenderAlignment`) builds a DOCX in-memory and asserts indices match the extractor's output — the regression net. HTML output is functional, not pixel-faithful: no Word styles, no images rendered, no list bullets.

---

## D-058: Annotation region schema flattened to block_indices for PDF + DOCX
**Status**: Active · **Date**: 2026-05-08
**Decision**: PDF and DOCX annotation regions both use `region: {block_indices: [N, ...]}` (single block, range, or arbitrary set) with `region: {block_index: N, row_range: [start, end]}` for table-row precision. The earlier `paragraph_indices` (DOCX) / `page+bbox`/`page+line_range` (PDF) split is removed. XLSX retains sheet/cells/row_range (different IR shape).
**Why**: PDF and DOCX extractors emit the same flat `DocumentIR` with sequential `ContentBlock.position.index`. Using paragraph/table/page indices forced a translation step that could drift or miscount. Single shape simplifies the validator, the UI, and Cline's rule-derivation. Row-range survives via `block_index + row_range`. Vs keeping the per-format split: makes the UI carry two region shapes for what's the same underlying data; Cline reads the same JSON either way.
**Consequences**: `cline-playbooks/annotation-schema.md` updated; `bootstrap.md` and any future schema readers must consume the new shape (its prose doesn't reference old field names, so no edit needed today; flagged). No on-disk annotations existed under the old schema, so no migration. PDF UI when built inherits the same shape — no new region type needed. Loses the ability to express "this PDF page" as a first-class semantic; if needed later, can be re-added as an alternate region.

---

## D-059: Reference annotation taxonomy — 5 first-class kinds + optional target ground truth + reference_list pattern
**Status**: Active · **Date**: 2026-05-09
**Decision**: Annotation schema's reference handling reorganized into 5 top-level kinds: `reference_intra_doc` (same-doc), `reference_cross_doc` (other plan/MNO), `reference_spec` (public standard, with required `style` field: `direct` | `indirect`), `reference_list` (the bibliography section), `reference_list_entry` (individual numbered entry, optional ground truth). The single old `references` kind with a `subkind` field is gone. Each reference kind accepts an optional `target` dict with kind-specific allowed keys for resolver-eval ground truth — explicitly **ignored by Cline's rule derivation**. Indirect spec citations (`[5]`) flow through a two-step resolution path that mirrors the existing `definitions_map` pattern: parser builds `reference_list_map: dict[int, {spec, section?}]` from the bibliography section, resolver looks up bracketed numbers in that map at resolve time. New `core/src/profiler/ANNOTATIONS.md` is the human-annotator's guide covering all 13 kinds with examples for every variant.
**Why**: (a) Flat picker UX is clearer than nested-subkind for hand-annotation. (b) Direct vs indirect spec citations are structurally different (the first has the spec name inline, the second has only a number that requires lookup) — encoding `style` as a required field forces the annotator to make the distinction up-front, avoiding a downstream parser branch on heuristics. (c) Capturing target as ground truth is cheap (one optional dict), preserves a future resolver-eval path, but doesn't tax the bootstrap loop because Cline ignores it. (d) Reusing the `definitions` section-level + per-entry pattern for `reference_list` is consistent with how the parser already handles glossaries — the same code path generalizes. (e) ANNOTATIONS.md lives under `core/src/profiler/` (not parser, not web) because the profiler is the module that turns annotation patterns into rules; matches the precedent of `core/src/query/RETRIEVAL.md`.
**Consequences**: 5 new kinds in `bootstrap_schema.KINDS` (was 9, now 13). `bootstrap_schema.SPEC_REFERENCE_STYLES`, `REFERENCE_LIST_NUMBERING_STYLES`, `REFERENCE_LIST_LAYOUTS`, `TARGET_KEYS_BY_KIND` are new public constants. `REFERENCE_SUBKINDS` and `REFERENCE_TARGET_KINDS` removed. Validator now requires `style` for `reference_spec` (validation error if missing). UI's KIND_FIELDS / KIND_ORDER / kind picker / CSS color classes updated. `parse_bootstrap.js` collects `target.<sub>` form keys into a nested `target` dict on save, splits back to dot-keys for edit. `bootstrap.md` BOOTSTRAP report shape gains 5 reference-flavor lines (was 1 parent block with 3 nested children). Resolver-eval ground-truth path is now unblocked but unwired — a future task reads `target` from saved annotations and compares against resolver output.
- **Parser plumbing for `reference_list_map`** [landed 2026-05-09 via the first BOOTSTRAP from VZW <PLAN0_NAME>+OTADM corpus]: `DocumentProfile.reference_list_section_pattern` + `reference_list_entry_pattern` schema fields; `RequirementTree.reference_list_map: dict[int, {spec, title?, section?}]` + `reference_list_section_number`; `_extract_reference_list` mirrors `_extract_definitions` (body-text scan + table-anchored layout, first-occurrence wins). `ParseStats.refs_extracted` counter. Resolver consumer for indirect spec citations (`reference_spec` with `style=indirect`) still pending — lands when first corpus has indirect spec annotations.

---

## D-060: Unified strike model — partial-text strike via runs; mark, don't drop, at extract time
**Status**: Active · **Date**: 2026-05-09. Partially supersedes D-031 (the geometric strike-line detection in PDF stays; only the *consequence* changes from "drop at extract" to "mark at extract; drop at parse").
**Decision**: A single rule for every strike across every format: **the extractor marks; the parser/UI decide**. The IR carries per-run strike state on every text-bearing block — paragraphs, headings, table cells — so downstream consumers can drop fully struck blocks (cascade) AND drop only the struck spans within partially-struck blocks (keep the rest). Concretely: new `TextRun` dataclass with `text` + `struck`; new `ContentBlock.runs` (paragraphs / headings), `header_runs`, `row_runs` (tables). Helpers `live_text()`, `row_all_struck(i)`, `header_all_struck()`, `cell_live_text(r, c)` rebuild content with struck runs filtered out. `font_info.strikethrough` is now a derived signal — True iff every textful run is struck — used by the parser's existing FR-33 cascade for fully-struck blocks. PDF and XLSX extractors **no longer drop** struck rows from the IR (was D-031 behavior). DOCX gets first-class partial-text strike across paragraphs, headings, and table cells.
**Why**: Three prior policies had three behaviors — paragraphs were mark-and-keep (parser decided), PDF/XLSX table rows were drop-at-extract (gone forever, no audit trail), DOCX table rows weren't detected at all. The drop-at-extract path destroyed information the user can never recover, even when wrong. Auditability + false-positive recovery + parser-time policy choice (`profile.ignore_strikeout`) all argue for "extractor neutral; parser drops; UI shows everything." Partial-text strike specifically is the user's primary need — within a sentence, a heading, or a table cell, only some characters may be struck (typo correction, requirement amendment). Whole-block strike loses too much. Vs leaving DOCX-tables as the only gap: that breaks parity and makes mental-model load high. Vs keeping the drop-at-extract path: blocks audit and recovery; the IR becomes lossy.
**Consequences**:
- IR schema: `TextRun`, `ContentBlock.runs`, `header_runs`, `row_runs`. Backward-compatible — empty defaults; `live_text()` falls back to `text` + `font_info.strikethrough` for legacy IRs.
- DOCX extractor: walks `paragraph.runs` and `cell.paragraphs[*].runs`, populates per-run strike state. Whole-block `font_info.strikethrough` is computed (every textful run struck) — replaces D-031's "any-run-struck" coarse heuristic.
- PDF extractor: keeps every row in `ContentBlock.rows`; populates `row_runs[i]` with single-run cells whose `struck` flag comes from existing geometric `_detect_struck_rows`. Whole-table `font_info.strikethrough` from `_table_is_struck` plus the all-rows-struck shortcut. Per-character partial-strike on PDF (would require per-span line testing) deferred to a future ADR.
- XLSX extractor: keeps every row; populates `row_runs[i]` from `cell.font.strike`. `header_runs` similarly. Whole-table strike on header-struck or all-rows-struck; preserves the prior "header struck → table dropped" semantic via `font_info.strikethrough`.
- Parser: post-cascade, normalizes `block.text` → `block.live_text()` and `block.rows` → drops fully-struck rows + per-cell live text. Mines req_ids from struck spans into `struck_req_ids` so they don't surface via table-anchored extraction. Cascade behavior on fully-struck section headings unchanged.
- UI: span-level strike rendering in IR pane (Bootstrap tab + Parse Review tab) and DOCX preview pane. Whole-row / whole-table strike applied at the `<tr>` / `<table>` level.
- Migration: existing PDF corpora were extracted with rows dropped. Re-extract under the new logic recovers those rows in the IR. Parser's parsed-tree output is unchanged for end-users (struck rows still drop at parse time). No data migration; just re-run extract.
- Tests: existing strike-drop assertions for PDF / XLSX inverted to assert "row kept; row_runs marks struck". New `test_strike_runs.py` covers model helpers, DOCX run population, and parser partial-strike normalization.
- D-031 remains the canonical entry for PDF strike-line geometric detection (`_table_is_struck`, `_detect_struck_rows`). D-060 changes only what's done with the detection result.

---

## D-061: User-driven content removal via `remove` annotations — rides on D-060 strike rails
**Status**: Active · **Date**: 2026-05-09. Builds on D-060.
**Decision**: New annotation kind `remove` — explicit human intent to exclude content from downstream pipeline (e.g., "skip the test-plan-mapping section until the test plans are ingested"). The Bootstrap UI captures regions to exclude (`block_indices` for whole blocks; `block_index + row_range` for table rows); a new pre-parse pass (`core/src/parser/user_annotations.py::apply_user_annotations`) reads `<env_dir>/annotations/<doc_id>_annotations.json` and **mutates the IR by setting strike marks on the listed regions** (every textful `TextRun.struck=True`; `font_info.strikethrough=True` on the block). The parser's existing FR-33 cascade then drops the content uniformly — section-level cascade fires automatically when the marked block is a heading. Pipeline parse stage (`core/src/pipeline/stages.py`) calls the helper before `parser.parse(ir)` for each doc and accumulates a `user_removes` count for the compact RPT. Companion fix: `_heading_depth` now also returns `block.level` for `BlockType.HEADING` blocks (DOCX-style headings) — the cascade was a latent bug for genuinely-struck DOCX headings, also surfaced by remove-on-DOCX-heading.
**Why**: A general-purpose "exclude this from ingestion" knob is needed independently of source-document strike marks. Examples: a section refers to plans not yet ingested (broken downstream refs); a table is known to be incorrect or duplicated; a heading + content needs deferral while triage finishes. Vs a separate "exclusion list" YAML or DB table: every exclusion file would need its own rendering, validator, and parser hook — three more moving parts. By riding on the strike rails the user already mastered (D-060), every exclusion gets the same auto-cascade, partial-text safety, and visual rendering for free. Vs a soft "ignore" hint on annotations: would create two parallel drop paths (strike vs ignore) with subtly different cascade semantics; one rail is simpler. The drop is reversible at parse time — delete the annotation, re-run parse; nothing is lost from the IR (matches D-060's "extractor is neutral; parser drops; UI shows everything"). Vs editing the source document: out of scope (the source is authoritative; NORA shouldn't mutate it).
**Consequences**:
- New `remove` kind in `bootstrap_schema.KINDS` (was 13, now 14). No required fields; supports both region shapes; reuses the existing `notes` field for the human reason (≤30 chars).
- New module `core/src/parser/user_annotations.py` — `apply_user_annotations(ir, path) -> int`. Idempotent and side-effect-free for missing/malformed files (logs warning, returns 0).
- `core/src/pipeline/stages.py` parse stage applies user annotations before `parser.parse(ir)` for every doc. Adds `user_removes` to stats dict. No CLI flag needed — annotation file presence is the trigger.
- `_heading_depth` honors `BlockType.HEADING` + `block.level` (DOCX); fixes a latent bug for struck DOCX headings AND enables remove-with-cascade on DOCX. Tests cover both paths.
- UI: `remove` in kind picker under a "User overrides" subheading; CSS color (red — delete intent); rendered with the existing `docx-struck` styling so the visual signal is consistent with strikethrough.
- Annotations file is now load-bearing for the pipeline (parse stage reads it). Pre-D-061 it was purely a Cline-bootstrap input. Schema-version field on the file (`version: 1`) gates forward compatibility — the loader silently ignores unknown future versions, so older code reading newer files won't crash.
- ANNOTATIONS.md gains a `remove` section documenting when to use it and example payloads (whole section, paragraph, table-row range).
- Tests: `test_user_annotations.py` (apply mechanics + parser-after-apply cascade); `test_strike_runs.py` (DOCX HEADING cascade fix); `test_parse_bootstrap.py` (schema validation).
- Reversibility: delete the annotation → next parse run treats the content as live again. The IR is never modified on disk by the apply step (mutation is in-memory during parse).

---

## D-062: Placeholdered profiles + per-bootstrap mappings + runtime substitution
**Status**: Active · **Date**: 2026-05-09. Replaces the leaky `<mno>_<plan>_profile.json` naming convention introduced under D-059's first commit (which exposed proprietary plan names in the public mirror).
**Decision**: Profiles for proprietary corpora carry **redaction placeholders** in their regex strings (e.g., `<MNO0>_REQ_<PLAN>_\d+`) and are filed by **opaque bootstrap IDs** — `customizations/profiles/bs_<8 hex chars>.json` — with no MNO / plan / release info in filename or content. The placeholder→real-value mapping lives in `customizations/mappings/<bootstrap_id>.json`. At parse time, `core/src/profiler/profile_substitute.py::load_substituted_profile()` reads the profile, finds the matching mapping (snapshot first, then `<env_dir>/state/cline-mapping.json` fallback), and walks every regex-string field substituting specific placeholders (`<MNO0>` → `re.escape("VZ")`) and generic placeholders (`<PLAN>` → `[A-Z0-9_]+` regex char class). **The trust boundary keeping mappings off the public mirror is the work-PC `pre-push` hook installed by `~/work/utils/git-sync/sync-work.sh`** — it blocks any `git push` whose remote URL contains `github.com` (override: `NORA_ALLOW_PUBLIC_PUSH=1`). The mappings directory is **NOT** gitignored — that lets team members share one canonical mapping via the company-internal git remote. The hook (not `.gitignore`) is what enforces the public-mirror exclusion.
**Why**: D-059's first commit shipped `bs_d7a2c81f.json` to public github, which leaked: (a) the MNO short prefix in the filename, (b) plan names in `created_from`, `_provenance.notes`, and sample IDs, (c) the existence of those specific proprietary plans. Even if mapping snapshots stay private, a profile filename and content that name the corpus is enough to identify the customer. Vs continuing the per-MNO naming + carefully redacting content: subtle and prone to slipping. Vs encrypting profiles: adds a key-management surface and breaks every `git diff` workflow. Vs treating *all* profiles as private: the existing `vzw_oa_profile.json` is for a publicly-distributable corpus and is intentionally public; we want both modes to coexist. Bootstrap IDs are opaque hex (no date / no semantic content) — easier to reason about across multiple bootstraps without revealing chronology. Runtime substitution rather than pre-substitution-at-commit-time keeps the public artifact static and reproducible regardless of which work PC consumes it.
**Consequences**:
- New module `core/src/profiler/profile_substitute.py` — `substitute_placeholders(profile, mapping)`, `load_substituted_profile(profile_path, env_dir=None)`, `find_mapping_file(...)`, `_normalize_mapping(...)` to handle both Cline's live forward-redaction shape and the snapshot reverse shape.
- `core/src/pipeline/stages.py` parse-stage swaps `DocumentProfile.load_json` → `load_substituted_profile`. Profiles without a matching mapping load unchanged (covers the public corpus case `vzw_oa_profile.json`).
- `customizations/mappings/` added with `.gitkeep` + `README.md`. **NOT gitignored** — committed and pushed to company-internal git so the team shares one canonical mapping. The work-PC pre-push hook (installed by `sync-work.sh`) is the boundary that keeps the directory off the public mirror.
- Pre-push hook installed by `sync-work.sh` on every sync (idempotent). Defends against `git push origin` calls bypassing the sync script. Override `NORA_ALLOW_PUBLIC_PUSH=1` is for auditable history-rewrite force-pushes.
- `cline-playbooks/bootstrap.md` updated: new Step 1 (bootstrap_id read-or-generate), new Step 8 (mapping snapshot write), report header gains `bootstrap_id: bs_<id>` line. Derived regex strings emit placeholders directly.
- `cline-playbooks/mapping.md` extended: dual-mapping table (live vs snapshot), shape distinction (forward-redaction vs reverse), trust-boundary note (pre-push hook, not gitignore).
- `.clinerules/02-content-safety.md` extended: mapping snapshot location, trust-boundary note (pre-push hook).
- Existing leaky profile (`customizations/profiles/bs_d7a2c81f.json` introduced in commit `2f918a6`) deleted in this change. Forward fix done; **history rewrite (separate operation, requires force-push)** removes the file from history along with residual proprietary string mentions in commit messages.
- New tests in `test_profile_substitute.py` cover: specific + generic substitution; mapping shape normalization (both directions); fallback chain (snapshot → env_dir/state → no-op); load_substituted_profile end-to-end.
- Generic placeholder defaults: `<MNO>` → `[A-Z]{2,4}` (typical 2-4 letter MNO codes — VZ / TM / ATT). Future MNOs with longer codes need a profile-side override or a default broadening; flagged as a future limitation when seen.

## D-063: Generic-rules pivot — profile-driven DOCX parsing replaces per-corpus bootstrap annotation
**Status**: Active · **Date**: 2026-05-10. Pivots away from D-054/D-055/D-056 — user reviewed work-PC IR JSON samples (toc / sections / struck / vershist / glossary) and concluded structural patterns are general enough to encode as profile rules without manual annotation per corpus.
**Decision**: 5-phase parser overhaul. (Phase 1) Profile schema deltas: `TocDetection` class; `RequirementIdPattern.anchor: "last_run"|"trailing_text"|"leading_text"` + `.normalize: "upper"|"none"`; rename `revision_history_heading_pattern` → `revision_history_label_pattern` (with `_from_dict` migration); `definitions_table_term_column` / `_definition_column`; `embed_glossary`. (Phase 2) Runs-over-text invariant for value extraction; `_heading_req_id()` dispatches on anchor mode. (Phase 3) Style-driven TOC pre-pass + `_toc_lookup()` pair-by-req_id-or-title + `docx_styles` heading classification; `toc_pair_misses` counter + `parser.format_error: kind=toc_pair_miss` WARN. (Phase 4) Front-matter cutoff = `max(toc_end, revhist_end)`, gated on `toc_detection.style_pattern` so OA-style numbering corpora keep their inline-only revhist consume (revhist sits inside chapter 1 in OA — applying the cutoff there would drop chapter 1's heading). (Phase 5) Glossary table-form support + `embed_glossary=False` drops glossary subtree from RAG/KG while preserving `definitions_map` for body-chunk acronym expansion.
**Why**: Manual annotation per corpus didn't scale — user wanted to onboard a 135-doc DOCX corpus without typing rules document-by-document. Real DOCX corpora share more structure than OA-style PDFs: paragraph styles encode heading depth (`Heading N`), TOC is auto-generated by Word with `toc N` styles AND embedded section numbers, runs separate title from trailing req_id, glossary tables follow a canonical 2-column shape. All of these are stable enough to profile-drive. The bootstrap loop (D-054/D-055/D-056) is preserved as the escape hatch for unusual corpora — profile defaults can disable the new path per-corpus (`heading_detection.method` switch, empty `toc_detection.style_pattern`). Vs (a) keep manual-annotation only: doesn't scale; (b) global heuristic switching: fragile; (c) chosen: profile-driven opt-in per-corpus.
**Consequences**:
- ~880 LOC across `core/src/parser/structural_parser.py`, `profile_schema.py`, `profile_substitute.py`, `chunk_builder.py`, `parse_log.py`, `parse_review.py`; ~880 LOC of tests (+52 tests: test_last_run_req_id.py, test_toc_pairing.py, test_glossary_skip_from_rag.py + extensions).
- New WARN namespace `parser.format_error` for graceful-recovery cases (`empty_runs_heading`, `concatenated_run_heading`, `toc_pair_miss`) — surfaces source-doc formatting errors without failing the parse.
- Work-PC corpus validated end-to-end: `reqs=13372 defs=1410 toc=19209 frontmatter=998 toc_pair_misses=5` (all 5 are real human source-doc errors).
- Profile knobs: a non-DOCX corpus or one that doesn't fit can disable the new path via empty `toc_detection.style_pattern` (cutoff disabled) or `heading_detection.method = "numbering"` (classification falls back to OA-style numbering pattern).
- BlockType.HEADING routing fixed in body pass (was PARAGRAPH-only); same fix applied to revhist consume break. Documented as part of the pivot.

## D-064: Skip-resolve + skip-standards — independent pipeline stage skips with one-way cascade
**Status**: Active · **Date**: 2026-05-10.
**Decision**: New first-class skip flags via the 3-tier config chain (CLI > env var > `config/llm.json` > per-env > default `False`). `--skip-resolve` / `--skip-standards` CLI flags; `NORA_SKIP_RESOLVE` / `NORA_SKIP_STANDARDS` env vars; `LLMConfigFile.skip_resolve` / `.skip_standards`; `EnvironmentConfig` overrides. `skip_resolve` implies `skip_standards` (one-way cascade — the standards stage reads resolve's manifest_dir as input). The reverse is not enforced — explicit `--skip-standards` alone doesn't force `skip_resolve`.
**Why**: Matches the existing `skip_taxonomy` / `skip_graph` shape (D-044), so users get a uniform mental model. Enables fast iteration cycles during parser development (skip the slow standards download) and offline operation (no HF / 3GPP network). Downstream tolerance was verified: `graph._load_manifests` returns empty on missing dir; `_load_reference_index` already handled missing file (no graph regression).
**Consequences**:
- 4 new symbols in `core/src/env/config.py` (env var consts + `resolve_skip_resolve` / `resolve_skip_standards`).
- `EnvironmentConfig` per-env override fields.
- `run_cli.py` adds 2 argparse flags + cascade logic + stage-filter note.
- 2 new precedence tests (`test_resolve_skip_resolve_3tier`, `test_resolve_skip_standards_3tier`).
- `--skip-resolve --skip-standards --skip-taxonomy --skip-graph` is now the canonical "extract → parse → vectorstore only" fast-iteration combination.

## D-065: Cross-encoder reranker plumbed into production query path via 3-tier + Config-page DB knobs
**Status**: Active · **Date**: 2026-05-10.
**Decision**: Two new knobs, both flowing through the unified resolver chain (env var > Config-page DB > `config/llm.json` > per-env > default):
- `reranker_enabled: bool = False` — when True, `_get_or_build_pipeline` in `web/routes/query.py` constructs a `CrossEncoderReranker` and plumbs it into `QueryPipeline`. False (default) → `MockReranker` passthrough = previous production behavior.
- `reranker_model: str = ""` — empty falls back to `DEFAULT_RERANKER_MODEL` (`cross-encoder/ms-marco-MiniLM-L6-v2`). Accepts a HuggingFace model id OR a local filesystem path. Local paths sidestep the online HF download when the host is firewalled.

Per-query-type gating (`_TYPE_RERANK_ENABLED`) still applies after the reranker is attached — FACT / CROSS_DOC / FEATURE_LEVEL / STANDARDS_COMPARISON / CROSS_MNO_COMPARISON / TRACEABILITY / RELEASE_DIFF rerank; SUMMARIZE / SINGLE_DOC / GENERAL passthrough.
**Why**: Until today, the production query pipeline always ran with MockReranker because `_get_or_build_pipeline` never constructed one — the cross-encoder existed only in the eval stage. User wanted to test BGE rerankers locally on a firewalled work PC; the existing code couldn't accept either an off-default model or a local-filesystem path. Default-False preserves current eval baselines (the 2026-05-08 A11 result showed MiniLM was net-zero on telecom queries; we don't want to silently flip retrieval behavior). Local path support enables the firewalled-host workflow without code changes — pre-download with `huggingface-cli download <id> --local-dir <path>`, point the knob at the path.
**Consequences**:
- 2 new resolver functions (`resolve_reranker_enabled`, `resolve_reranker_model`); 2 new env vars; 2 new LLMConfigFile + EnvironmentConfig fields; 2 new ConfigField entries on the Config page.
- New `_resolve_reranker()` helper in `web/routes/query.py` — falls back to MockReranker silently on init failure (so a missing local cache doesn't crash the request).
- `DEFAULT_RERANKER_MODEL` constant. Suggested telecom-friendly upgrade: `BAAI/bge-reranker-base`.
- 2 new precedence tests.
- Once enabled with a good model, may shift retrieval rankings — eval baselines need a refresh comparison.

## D-066: Generic placeholders always substitute, regardless of mapping presence
**Status**: Active · **Date**: 2026-05-10. Fixes a behavior inconsistency in D-062's `load_substituted_profile`.
**Decision**: `load_substituted_profile` calls `substitute_placeholders(profile, mapping or {})` unconditionally. Previously, when no mapping snapshot was found, it returned the profile *without* calling `substitute_placeholders` at all — generic placeholders (`<PLAN>` / `<DIGITS>` / `<MNO>` / `<REL>`) stayed as literal text in compiled regexes despite the module docstring describing them as mapping-independent.
**Why**: The bug surfaced on the work PC when the user hand-edited `<MNO0>` → `VZ` in their profile JSON as a workaround for an unrelated `find_mapping_file` lookup issue. The substituted pattern became `VZ_REQ_<PLAN>_\d+` — literal `<PLAN>` substring, matching zero req_ids — and the chunk builder dropped all 13,425 requirements (chunks=0). The early-return was an oversight, not an intentional design. The module docstring already documented generic placeholders as "mapping-independent — substitute even when no mapping snapshot is found." Now the implementation matches the stated semantics.
**Consequences**:
- A pre-existing test (`test_no_mapping_returns_profile_unchanged`) had asserted the wrong direction (codified the bug). Updated to `test_no_mapping_still_substitutes_generic_placeholders`.
- New regression test (`test_workaround_user_replaced_specific_in_profile`) mirrors the user's hand-edited-profile shape.
- Public corpora (`vzw_oa_profile.json`) have no placeholders, so substitution is a no-op — zero behavior change for them.
- Specific placeholders without mapping entries still emit WARN log (existing behavior in `substitute_placeholders`) — caller can spot the un-substituted `<MNO0>` etc. and either provide a mapping or hand-edit.

## D-067: Per-chunk retry-with-shrink + skip-on-failure for Ollama 5xx, instead of failing the stage
**Status**: Active · **Date**: 2026-05-10.
**Decision**: `OllamaEmbedder` now retries HTTP 5xx responses with the text halved, up to `_MAX_SHRINK_RETRIES` (=2) attempts. After exhausted retries, raises a new `ChunkEmbeddingError(idx, preview, attempts, last_error)`. `VectorStoreBuilder._embed_batched` catches this per batch, falls back to one-at-a-time embedding for that batch (so the rest still embed), and records failed indices. The `build()` caller filters failed indices from ids/texts/metadatas before `store.add()` so the vector store stays internally consistent. 4xx responses propagate unchanged (no point retrying a bad model name / malformed request). Non-HTTP errors (DNS, refused, timeout) also propagate — those signal a server-level problem the caller must handle.
**Why**: A specific token-dense chunk from one plan kept failing at the 8000-char truncation cap with HTTP 500 — likely an Ollama-side token-budget overrun for unusually dense content. The previous behavior raised on first per-chunk failure → ~5 minutes of embedding work discarded per attempt. Vs (a) reducing the default `max_input_chars`: blanket regression for all chunks; (b) token-aware truncation (count true tokens via a tokenizer): bigger change, similar gain; (c) chosen: surgical retry-with-shrink, then skip. A handful of skipped chunks lose retrieval coverage but the rest of the pipeline finishes; the skipped chunk_ids are logged (capped at 10 per log line) for architect audit.
**Consequences**:
- New `ChunkEmbeddingError` exception class in `embedding_ollama.py` — caught specifically by builder; other RuntimeError subclasses still abort.
- `_embed_batched` return type changes from `list[list[float]]` to `tuple[list[list[float]], list[int]]` (skipped indices alongside the embeddings).
- Skipped chunks have no retrieval representation. If a query needs them, the query simply doesn't return them — no fabrication. WARN log surfaces the gap.
- 3 new tests (retry-success / exhausted-retries / 4xx-no-retry).
- A follow-up item (Next section: "Token-dense chunks skipped at embed time in one specific plan") tracks the longer-term fix (token-aware truncation OR per-row chunking for table-heavy reqs).
