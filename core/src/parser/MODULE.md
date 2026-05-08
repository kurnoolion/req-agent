# parser

**Purpose**
Generic, profile-driven structural parser. Consumes a `DocumentIR` + `DocumentProfile` and emits a `RequirementTree` — the typed, hierarchical form of the document that every downstream stage (resolver, graph, taxonomy, vectorstore) reads. Serves FR-3 (profile-driven generic parser; no per-MNO code paths), FR-31 (priority extraction), FR-32 (applicability inheritance), FR-33 (struck-block drop), FR-34 (TOC drop), FR-35 (definitions extraction). Implements D-003 (MNO behavior lives in profile, not code), D-030 (applicability inheritance), D-031 (struck-block drop semantics), D-032 (per-document definitions map on `RequirementTree`), D-043 (acronym lookup chain — parser fix recovers misclassified header rows).

**Public surface**
- `GenericStructuralParser` (structural_parser.py) — the parser; consumes `DocumentIR` + `DocumentProfile`, returns `RequirementTree`
- `RequirementTree` (structural_parser.py) — top-level output: plan-level metadata + flat `requirements` list + `definitions_map: dict[str, str]` (FR-35 [D-032]) + `parse_stats` (incl. `struck_blocks_dropped: int` per [D-031], `cascade_blocks_dropped: int` per [D-037], `toc_blocks_dropped: int` per FR-34, `revhist_blocks_dropped: int` per FR-34 [D-035], `defs_extracted: int` per FR-35); `to_dict`, `save_json`, `load_json`; transient `parse_log: ParseLog | None` (not serialized to tree JSON — written separately by the pipeline stage)
- `ParseLog` (parse_log.py) — per-document parse transparency log; written to `<env_dir>/reports/parse_log/<doc_id>_parse_log.json`; carries `dropped_blocks: list[DroppedRange]`, `toc: SectionRange | None`, `revision_history: SectionRange | None`, `glossary_section: GlossaryInfo | None`, `acronyms: list[AcronymEntry]`, `summary: ParseLogSummary`
- `DroppedRange` — contiguous run of dropped blocks: `block_start`, `block_end`, `page_start`, `page_end`, `block_count`, `reason` (`"toc" | "revhist" | "text_strikethrough" | "cascade"`)
- `SectionRange` — block/page span for a named drop section (TOC, revision history)
- `GlossaryInfo` — glossary section location: `section_number`, `section_title`, `block_start`, `block_end`, `page_start`, `page_end`, `acronym_count`
- `AcronymEntry` — single extracted acronym: `acronym`, `expansion`, `source` (`"table" | "body_text"`)
- `ParseLogSummary` — aggregate drop counts + `glossary_acronyms`
- `Requirement` — single requirement node: `req_id`, `section_number`, `title`, `parent_req_id`, `parent_section`, `hierarchy_path`, `zone_type`, `priority` (FR-31), `applicability: list[str]` (FR-32 [D-030]), `text`, `tables`, `images`, `children`, `cross_references`
- `TableData`, `ImageRef`, `StandardsRef`, `CrossReferences` — nested types
- `parse_review.generate_template(log_path)` — build a pre-populated review JSON template from a `*_parse_log.json` file; written to `<doc_id>_parse_review.json` by the CLI
- `parse_review.generate_compact_report(review_path, log_path)` — read a completed review JSON → return compact PLG-CHK report string for pasting into chat; auto-detects sibling parse_log if `log_path` omitted
- `parse_review_cli.main` — CLI: `create <parse_log.json>` / `create-all <dir>` / `report <review.json>`
- `parse_cli.main` — CLI entrypoint (`python -m core.src.parser.parse_cli`)

**Invariants**
- Parser is **LLM-free**. Any downstream LLM enrichment (taxonomy, query synthesis) happens in its own module; the structural layer stays deterministic and cheap to re-run.
- No per-MNO branches. A new MNO is onboarded by running the profiler on its docs, editing the resulting profile, and re-running the parser — no parser code change.
- `RequirementTree.requirements` is a flat list in document order. Parent/child relationships are encoded via `parent_req_id` / `children` ID references; consumers reconstruct the tree if they need traversal.
- **Every Requirement is anchored from exactly one source block** — either a paragraph anchor (heading-style block, or a small-font standalone-ID paragraph), or a table-cell anchor (a row whose cell matches the profile's `requirement_id.pattern`). Paragraph anchors win on duplicate `req_id`s; the table-anchor pass dedups against the paragraph-anchor set.
- Table-anchored Requirements have `section_number=""` by design — they're addressed by `req_id` and linked to their owning paragraph-anchored section via `parent_section` / `parent_req_id`. Consumers must not assume `section_number` is non-empty.
- `hierarchy_path` mirrors the heading chain from root down to the requirement — used by the graph and vectorstore to preserve structural context when chunking or indexing. Table-anchored Requirements inherit `hierarchy_path` from their parent paragraph-anchored section.
- Cross-references are structurally detected (regex from profile) but **not resolved** here. `CrossReferences.internal/external_plans/standards` are raw strings; [resolver](../resolver/MODULE.md) turns them into concrete manifests.
- `zone_type` is copied from the profile's `DocumentZone` match — used by the graph to route requirements to the right subgraph partition. Table-anchored Requirements inherit `zone_type` from their parent.
- `applicability` resolves in document order via a post-pass after `_link_parents`: explicit value on the requirement wins; else inherit from `parent_section`'s already-resolved value; else fall back to the document-level applicability section's value, if any; else empty list (downstream stages do not filter on empty) [D-030].
- Struck-through blocks (`block.font_info.strikethrough == True`) are skipped entirely by `_build_sections` when `profile.ignore_strikeout == True` (default). The IR retains them; only the parser-level drop is gated by the profile toggle [D-031].
- **Struck section headings cascade** [D-037]: when a struck paragraph block is also a section heading (per `_classify_heading`), `cascade_depth` is armed to that heading's depth. Subsequent blocks (paragraphs, tables, images) are dropped until a new heading appears at depth ≤ `cascade_depth` — a sibling or shallower section. Deeper-nested struck headings inside an already-cascading section don't tighten the boundary; only shallower struck headings do. Counter: `ParseStats.cascade_blocks_dropped`.
- TOC entries (matching `profile.toc_detection_pattern`) are skipped before heading classification. Pages where ≥`toc_page_threshold` of blocks match are treated as TOC pages and dropped wholesale (FR-34).
- **Revision-history sections** (FR-34 [D-035]): a paragraph matching `profile.revision_history_heading_pattern` arms a consume state; the heading paragraph plus all subsequent non-paragraph blocks (tables and images) are dropped until the next paragraph block (which is by construction the next section's heading or some inter-section text). Multi-page revhist tables — pdfplumber emits each page's slice as its own table block — are consumed as a unit. Counter: `ParseStats.revhist_blocks_dropped`.
- The definitions / acronyms / glossary section is **kept** in the parsed tree; extraction populates `RequirementTree.definitions_map` *in addition to* leaving the section as a queryable Requirement [D-032]. The map is populated from BOTH layouts in the matched section: body-text via `definitions_entry_pattern`, and tables (col[0] = term, col[1] = expansion, whitespace collapsed); body-text scans first, then tables in document order; first-occurrence-wins on duplicate term [D-038]. **Table-header recovery [D-043]**: when `tbl.headers` looks like a definition row (not the canonical `Acronym | Definition` column-header — checked via a token-set match against a known canonical set: `acronym, term, definition, abbreviation, meaning, description, …`), it's folded into the candidates list. Compensates for markdown extractors that misclassify a row as a header when a `|---|` divider appears mid-table.
- Table-anchored Requirements inherit `applicability` (and `zone_type` as before) from their parent paragraph-anchored section via `_propagate_hierarchy_to_table_reqs` [D-030].

**Key choices**
- One `RequirementTree` per source document (not per MNO or release) — the unified graph is assembled later; keeping parse output 1:1 with input keeps re-runs incremental.
- Flat requirements list with ID refs rather than a nested tree — trivially JSON-serializable and safe to load partially (load header, skip body) for large plans.
- Parser reads the profile but never writes it — the profile is an input, edited only by the profiler or by a human. This enforces the corrections-override flow.
- Tables preserved with source tag (`inline` vs `embedded_xlsx`) so the graph and query layer can score table-derived answers differently from prose-derived ones.
- **Two req-ID anchor sources**: paragraph anchors (heading-block, pending-id resolution, or inline body-text id) and table-cell anchors (column-1-of-row first; all-cells fallback; one anchor per row max). Necessary because telecom requirement docs frequently define requirements through cross-reference tables — IDs that exist in tables but never as paragraph-form anchors. Detected against the same `requirement_id.pattern` regex from the profile, so adding a new MNO still requires no parser code change. Paragraph anchors win on duplicate `req_id`s to keep precedence deterministic.
- New parser passes added in document order (each strictly post-`_link_parents`): `_apply_applicability` [D-030] → `_extract_definitions` [D-032]. Strike-block and TOC drops happen earlier inside `_build_sections` because they affect what reaches the heading classifier.

**Non-goals**
- No semantic enrichment (feature tagging, standards resolution, embeddings) — done downstream.
- No content rewriting or summarization — parser preserves the source text verbatim inside each `Requirement.text`.
- No OCR or layout heuristics — those are extraction's job; parser trusts the IR.
- No schema migration — if `DocumentProfile` schema evolves, both sides change together.

<!-- BEGIN:STRUCTURE -->
_Alphabetical, regenerated by regen-map._


`parse_audit.py`
- `_audit_doc` — function — internal — Build audit rows for one parsed tree, in document order.
- `_CSV_HEADERS` — constant — internal
- `_DEPTH_HIGH_CONFIDENCE_MAX` — constant — internal
- `_DEPTH_RUNAWAY_THRESHOLD` — constant — internal
- `_score_row` — function — internal — Return (confidence, reason) for a single requirement.
- `_summarize` — function — internal
- `_TITLE_MAX_LEN` — constant — internal
- `_TITLE_TINY` — constant — internal
- `_write_csv` — function — internal
- `AuditRow` — dataclass — pub
- `main` — function — pub

`parse_cli.py`
- `main` — function — pub

`parse_log.py`
- `AcronymEntry` — dataclass — pub — A single term → expansion pair extracted from the glossary section.
- `DroppedRange` — dataclass — pub — Contiguous run of dropped content blocks sharing a drop reason.
- `GlossaryInfo` — dataclass — pub — Location and content summary of the definitions/acronyms section.
- `ParseLog` — dataclass — pub — Complete parse transparency log for one document.
  - `save_json` — method — pub
- `ParseLogSummary` — dataclass — pub
- `SectionRange` — dataclass — pub — Block / page span for a named drop section (TOC, revision history).

`parse_review.py`
- `_NOTE_MAX` — constant — internal
- `_trunc` — function — internal
- `generate_compact_report` — function — pub — Read a completed review JSON and return a compact report string suitable
- `generate_template` — function — pub — Build a pre-populated review template from a parse_log JSON file.

`parse_review_cli.py`
- `cmd_create` — function — pub
- `cmd_create_all` — function — pub
- `cmd_report` — function — pub
- `main` — function — pub

`structural_parser.py`
- `_canonicalize_req_id` — function — internal — Normalize whitespace in a matched req_id to underscores.
- `_HEADING_MAX_LEN` — constant — internal
- `_REQ_ID_WHITESPACE_RE` — constant — internal
- `_SECTION_NUM_RE` — constant — internal
- `CrossReferences` — dataclass — pub
- `GenericStructuralParser` — class — pub — Profile-driven structural parser for requirement documents.
  - `__init__` — constructor — pub
  - `_append_text` — staticmethod — internal — Append text to a section, with paragraph separation.
  - `_apply_applicability` — method — internal — FR-32 [D-030]: resolve `Requirement.
  - `_build_hierarchy_path` — staticmethod — internal — Build the hierarchy path from root to this section.
  - `_build_parse_log` — method — internal — Assemble the ParseLog from the drop and heading entries collected
  - `_build_sections` — method — internal — Build the flat list of sections with hierarchy info from content blocks.
  - `_classify_heading` — method — internal — Check if a block is a heading.
  - `_classify_zone` — method — internal — Classify a section into a document zone using profile rules.
  - `_create_table_anchored_req` — method — internal — Append a Requirement node anchored by a table row.
  - `_extract_applicability_labels` — method — internal — Run requirement_patterns over `text`; first match wins.
  - `_extract_cross_refs` — method — internal — Extract cross-references from section text.
  - `_extract_definitions` — method — internal — FR-35 [D-032]: extract `term -> expansion` pairs and the
  - `_extract_plan_id_from_req` — method — internal — Extract the plan ID component from a requirement ID using profile config.
  - `_extract_plan_metadata` — method — internal — Extract plan-level metadata using profile patterns.
  - `_extract_priority` — method — internal — Extract a priority marker from heading text (FR-31).
  - `_extract_standards_releases` — method — internal — Extract referenced standards releases from the document.
  - `_extract_table_anchored_reqs` — method — internal — Detect req-IDs in table cells; append child Requirement nodes to `sections`.
  - `_find_req_ids` — method — internal — Find all req_id patterns in `text` and canonicalize each.
  - `_glossary_section_range` — method — internal — Return (block_start, block_end, page_start, page_end) for the
  - `_identify_toc_pages` — method — internal — Return the set of page numbers classified as TOC pages (FR-34).
  - `_is_req_id_block` — method — internal — Check if a block is a standalone requirement ID (small font).
  - `_link_parents` — method — internal — Build parent-child relationships and hierarchy paths.
  - `_looks_like_definition_column_header` — staticmethod — internal — True when (h0, h1) looks like the canonical column-header
  - `_propagate_hierarchy_to_table_reqs` — method — internal — Copy parent's hierarchy_path to table-anchored Requirements.
  - `parse` — method — pub — Parse a document IR into a structured requirement tree.
- `ImageRef` — dataclass — pub
- `ParseStats` — dataclass — pub — Per-document parser diagnostics.
- `Requirement` — dataclass — pub
- `RequirementTree` — dataclass — pub
  - `load_json` — classmethod — pub
  - `save_json` — method — pub
  - `to_dict` — method — pub
- `StandardsRef` — dataclass — pub
- `TableData` — dataclass — pub
<!-- END:STRUCTURE -->

**Depends on**
[models](../models/MODULE.md), [profiler](../profiler/MODULE.md), [extraction](../extraction/MODULE.md) (as upstream producer).

**Depended on by**
[resolver](../resolver/MODULE.md), [vectorstore](../vectorstore/MODULE.md), [taxonomy](../taxonomy/MODULE.md), [standards](../standards/MODULE.md), [graph](../graph/MODULE.md), [pipeline](../pipeline/MODULE.md).
