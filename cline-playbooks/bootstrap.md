# Playbook: bootstrap

**Purpose**: derive **initial** detection rules from human-annotated corpus files. Use this
once per stage when a new corpus or new structural kind is being onboarded — before any
parser/profile rules exist for it.

**When to use this vs `derive-rule.md`**:
- `bootstrap.md` — when human annotations exist (`<env_dir>/annotations/<plan>_annotations.json`)
- `derive-rule.md` — fallback when no annotations exist; Cline samples the corpus directly
- `feedback-loop.md` — refinement after the parser has run and humans have reviewed output

**When to use this vs `feedback-loop.md`**:
- `bootstrap.md` — Day 0; cold start from annotations
- `feedback-loop.md` — Day N; refinement from Parse Review feedback

**Input**: list of annotated docs (or "all" to use every annotation file under
`<env_dir>/annotations/`).

## Steps

1. Read `cline-playbooks/annotation-schema.md` so you know the schema.
2. For each annotated doc:
   - Validate the annotation file per the schema.
   - Open the source doc (`extract` stage IR if available; else read raw).
   - For each annotation, locate the region in the doc's IR.
   - **Read the verbatim text at the region locally** to use for rule derivation. Verbatim
     text NEVER leaves Cline — it's only used to derive the abstract rule.
3. Group annotations by `kind` across all docs.
4. For each kind:
   - **Derive a rule** that matches all annotated examples (the union of regions across docs).
   - **Compute self-coverage**: TP = annotations the rule matches when re-run on the source.
   - Note: there are no negative annotations, so FP rate isn't measurable from annotations
     alone — that's caught by the feedback loop later.
5. For reference kinds: derive separate detection rules for each of the 5 reference kinds (`reference_intra_doc`, `reference_cross_doc`, `reference_spec` with `style=direct` and `style=indirect` as separate sub-rules, `reference_list` section pattern, `reference_list_entry` per-entry pattern). Indirect spec citations have a two-step pipeline path: parser detects `[N]` at source → looks up entry N in the doc's `reference_list_map` → resolver hits the standards graph. The `target` dict on annotations is **ignored for rule derivation** — it's reserved for resolver-eval ground truth.
6. Apply mapping forward-redaction to all output values (per `02-content-safety.md`).

## Output: `BOOTSTRAP` report shape (apply mapping; max 25 lines)

```
BOOTSTRAP v=1 docs=<N> kinds=<M> annotations=<total>
prov: <PLAN0>, <PLAN1>, <PLAN2>      ← which plans contributed annotations
mapping: v=<N> entries=<N>

section_heading:           <regex or pattern>     sigma=<N> TP=<N>
req_id:                    <regex>                sigma=<N> TP=<N>
toc:                       <heuristic>            sigma=<N> TP=<N>
strikethrough:             <heuristic>            sigma=<N> TP=<N>
version_history:           <regex>                sigma=<N> TP=<N>
definitions:               <layout>               sigma=<N> TP=<N>
applicability:             <heuristic>            sigma=<N> TP=<N>
priority:                  <regex>                sigma=<N> TP=<N>
reference_intra_doc:       <regex>                sigma=<N> TP=<N>
reference_cross_doc:       <regex>                sigma=<N> TP=<N>
reference_spec_direct:     <regex>                sigma=<N> TP=<N>
reference_spec_indirect:   <regex>                sigma=<N> TP=<N>
reference_list_section:    <heading regex>        sigma=<N> TP=<N>
reference_list_entry:      <per-entry regex>      sigma=<N> TP=<N>

errors: <count> validation issues (if any)

ASK: generate initial profile.json schema for these kinds + parser code
     for the new kinds (references_*).
```

`sigma` = number of annotations the rule was derived from (provenance signal — more
annotations → more confident rule). `TP` = how many annotations the derived rule
correctly matches when run back on the source.

If a kind has fewer than 3 annotations, append a single line `LOW_PROV: <kind>` —
the rule is still derived but flagged as needing more annotation coverage.

## Validation errors

If annotation files have schema problems, list them after the per-kind block:

```
errors:
  <plan>_annotations.json: ann_007 missing 'region.page'
  <plan>_annotations.json: ann_012 'notes' exceeds 30 chars
```

Cap at 5 listed errors; append `(+N more — see <env_dir>/reports/cline/bootstrap-errors.log)`
if more. Cline writes the full error log on-prem.

## Rule-derivation hints per kind

- **section_heading**: combine numbering pattern + font-style if available + context
  (preceded by blank, followed by content). Output as a regex if numbering carries the
  full signal; else as a multi-clause heuristic.
- **req_id**: regex from token shape. Apply placeholders for MNO / PLAN substrings.
- **toc**: page-level pattern (≥X% of lines match leader-dot-page) plus
  `toc_page_threshold`.
- **strikethrough**: geometric heuristic (line count, width threshold, position relative
  to bbox) for PDFs; font-flag check for DOCX.
- **version_history**: regex for the heading + a window-bounded table-drop heuristic.
- **definitions**: layout description + column-header detection.
- **applicability**: position + content-shape (typically a parenthesized tag list).
- **priority**: regex or position-based marker.
- **reference_intra_doc**: regex matching section-number or req-id within the same doc's plan
- **reference_cross_doc**: regex matching plan-prefixed reference shape
- **reference_spec** (style=direct): regex matching `3GPP TS X.Y[, §Z]` and similar inline spec citation shapes
- **reference_spec** (style=indirect): regex matching bracketed/parenthesized numbered citations (`[5]`, `(5)`, etc) — derive separately from the direct pattern; report as `reference_spec_indirect` in the BOOTSTRAP block
- **reference_list**: section-heading regex (`^References$|^Bibliography$|...`) plus a layout hint (paragraph_list / two_col_table). Mirrors `definitions` — Teacher LLM will wire this to a `reference_list_map` in the parsed tree, parallel to `definitions_map`.
- **reference_list_entry**: per-entry regex with capture groups for `(number, spec, [optional section])`. Used by the parser to populate `reference_list_map`. The `target` field on annotations (when present) is resolver-eval ground truth, not rule-derivation input.

## Constraints

- **Maximum 25 lines** in the output report.
- Do NOT write to `customizations/profiles/<plan>/profile.json` — Teacher LLM does that.
  You ONLY emit the report.
- Do NOT commit anything to git. Stage 0 of the loop ends with the user typing the
  BOOTSTRAP report into Teacher LLM.
- Apply mapping forward-redaction to every output token.

## What Teacher LLM does next

After reading the BOOTSTRAP report, Teacher LLM:
1. Generates the initial `customizations/profiles/<plan>/profile.json` (or updates the
   existing one) with the derived patterns.
2. Generates parser code for any new `kinds` (e.g., `references_*` if not previously
   handled).
3. Commits to git.

You then `git pull`, run the parser, and proceed to Phase 4 (humans review via the Parse
Review web page) → `feedback-loop.md`.
