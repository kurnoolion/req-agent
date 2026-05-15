## D-DRAFT-1: Density gate (≥75% keyword density) layered on top of `definitions_section_pattern`
**Status**: Active · **Date**: 2026-05-16.
**Decision**: After `_extract_definitions` matches a section title via `definitions_section_pattern` (the legacy substring regex, default `(?i)acronym|definition|glossary`), apply a hardcoded density gate before accepting the match. Require ≥75% of the title's *meaningful* tokens to belong to a narrow keyword set (`glossary`, `definition[s]`, `acronym[s]`, `abbreviation[s]`, `term[s]`). Stopwords (`and`, `or`, `the`, `with`, `for`, `of`, `a`, `an`) and any embedded req_id token are stripped before counting. The helper (`_glossary_label_density` + the keyword/stopword sets + the `_GLOSSARY_LABEL_MIN_DENSITY = 0.75` threshold) lives in `structural_parser`; `parse_debug` imports it so the diagnostic preview and the production gate cannot drift apart.
**Why**: The legacy regex is a permissive substring match — it fires on any title containing one of the keywords, including non-glossary titles like "Section 2.3 Acronyms list and notes" (1/5 = 20% density) or "Performance Requirements: Acronyms used in this section" (1/7 = 14%). Real-corpus regression: these false positives surfaced as spurious glossary annotations on the Review tab. The strand's original goal was to build a full `GlossaryDetection` profile dataclass mirroring `RevhistDetection`'s three-signal scorer (heading-text + vocab + cell fingerprint), but in practice the missing piece causing user-visible bugs was just the vocab signal applied as a tightening gate, not a new detection path. The density rule is that signal in isolation.

Options considered:
- (a) Build the full `GlossaryDetection` schema field with three signals — bigger change, opens design decisions (defaults, weights, threshold-as-profile-knob); deferred.
- (b) Tighten `definitions_section_pattern` per-corpus — pushes complexity onto every profile owner; corpus drift makes tuning brittle.
- (c) **Chosen**: gate the existing regex match by density in the parser, with the threshold + keyword set hardcoded. Easy to add a profile knob later if a corpus needs different tuning.

**Consequences**:
- The density gate runs unconditionally — any corpus where the legacy regex was a true positive at <75% density now fails. So far no such cases observed; the 75% threshold tolerates connectives via stopword filtering.
- The full `GlossaryDetection` profile field remains deferred. If the corpus shows missed glossaries (regex misses entirely), a follow-up strand can build the three-signal scorer.
- The req_id stripping uses the *non-anchored* `_req_id_re` (substring strip), not `_req_id_anchored_re` (full-match) — embedded req_ids in titles get stripped correctly.
- Tests in `test_structural_parser_headings.py`: density rejects regex-matching FP titles; req_id strip preserves single-word glossary titles (e.g. `Glossary VZ_REQ_fooBar_12345` → 1/1 = 100%).
- Wire into the to-be-built `GlossaryDetection` field as the vocab signal when that strand opens.

## D-DRAFT-2: Drop docx + pdf "degenerate-table" filter that silently lost 1×1 and sparse content tables
**Status**: Active · **Date**: 2026-05-16.
**Decision**: In both `docx_extractor.py` and `pdf_extractor.py`, the table-shape filter changes from `len(non_empty_headers) <= 1 AND total_cells == 0` to `non_empty_headers == 0 AND non_empty_body == 0` — i.e. drop a table only when every cell across headers + body is empty. The PDF-specific 1×1-hallucination filter (pdfplumber fabricates these around small column-aligned text regions like VZW OA's small-font req_id markers) stays intact as a separate guard.
**Why**: The old filter shape accidentally dropped any table where ≤1 header cell had content AND the body was empty. That includes 1×1 content tables (Word commonly uses these as paragraph wrappers — a section's entire body in a single-cell table for layout purposes) and 1×N tables with one content cell. Real-corpus regression: a doc's next-section content (wrapped in a 1×1 table) was missing from `out/extract/<DOC>_ir.json`. The filter's stated intent — "single empty column" — never matched its implementation.

**Consequences**:
- More tables flow through to the parser. The parser already tolerates sparse and single-cell tables.
- PDF 1×1 hallucinations still get filtered by the dedicated guard immediately after.
- Three regression tests in `test_docx_extractor_merges`: single-cell content survives; truly empty 2×3 still dropped; 1×3 sparse-content survives.
- This fix is a prerequisite for D-DRAFT-3 (nested-table walk) — many of the nested tables that walk picks up live inside dropped wrappers, but some live inside wrappers that do carry surrounding text.

## D-DRAFT-3: Walk nested tables inside docx cells; emit each as its own TABLE block
**Status**: Active · **Date**: 2026-05-16.
**Decision**: In `docx_extractor.py`, after each top-level `<w:tbl>` block emits, recursively walk its cells' `cell.tables` (python-docx) and emit each nested table as its own TABLE block. Order: depth-first, parent-first-then-children, document order within each cell. Dedupe merged regions via `_tc` identity so a horizontally-merged cell isn't visited per-column. Run the nested walk even when the outer block was dropped as empty — a pure layout wrapper (1×1 with no surrounding text, only nested content inside) is empty by intent.
**Why**: `_table_block` reads only `cell.text` (paragraph text via python-docx), so tables nested inside cells were silently invisible. Real-corpus pattern: an outer 1×1 wrapper around a real 2-column glossary table (Acronym/Term | Definition) plus a trailing description paragraph. Before this fix the wrapper survived with `cell.text` = the trailing paragraph only — the actual acronym/definition rows never reached the IR, and the parser matched the glossary section by title but found zero entries. Word's natural way of placing content tables inside layout wrappers means nested tables aren't pathological; they're standard.

Options considered:
- (a) Flatten — treat the wrapper as a pass-through and emit only the nested table. Loses the wrapper's surrounding text (the trailing paragraph case).
- (b) Pre-walk cells to find nested tables; emit nested *before* parent — preserves OOXML document order strictly but inverts the natural recursion shape.
- (c) **Chosen**: emit parent first, then children. Slight document-order inversion within a single parent's scope, but trivially correct recursion, and the parser treats a section's tables as a bag for definitions extraction so the inversion is cosmetic.

**Consequences**:
- IR block count grows when wrappers are present; downstream consumers iterate tables by section so order-within-section is the main visible effect.
- Recursion is unbounded — any depth of nested tables is captured. No real-corpus case yet needs more than one level.
- Two regression tests in `test_docx_extractor_merges`: wrapper + trailing paragraph → two TABLE blocks (outer + nested); empty wrapper → outer dropped, nested survives.
- Does **not** address tables inside `<w:sdt>` content controls, `<w:txbx>` text boxes, or other non-`<w:tbl>` body containers — that remains a separate concern if a future corpus surfaces it.
