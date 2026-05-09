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

1. **Bootstrap ID** [D-062]. Read or generate the bootstrap_id:
   - If `<env_dir>/state/cline-bootstrap-id.txt` exists, read its single-line
     contents and use it as the bootstrap_id for this run.
   - Else, generate `bs_<8 random hex chars>` (e.g. `bs_a3f2b1c4`), write it
     to `<env_dir>/state/cline-bootstrap-id.txt` (just the id, single line, no
     trailing newline noise), and use it for this run.
   The bootstrap_id is opaque — it carries no MNO / plan / release info and is
   safe to embed in the public profile filename. Subsequent BOOTSTRAP runs on
   the same env reuse the same id so the placeholdered profile keeps growing
   instead of forking per session.
2. Read `cline-playbooks/annotation-schema.md` so you know the schema.
3. For each annotated doc:
   - Validate the annotation file per the schema.
   - Open the source doc (`extract` stage IR if available; else read raw).
   - For each annotation, locate the region in the doc's IR.
   - **Read the verbatim text at the region locally** to use for rule derivation. Verbatim
     text NEVER leaves Cline — it's only used to derive the abstract rule.
4. Group annotations by `kind` across all docs.
5. For each kind:
   - **Derive a rule** that matches all annotated examples (the union of regions across docs).
   - **Compute self-coverage**: TP = annotations the rule matches when re-run on the source.
   - Note: there are no negative annotations, so FP rate isn't measurable from annotations
     alone — that's caught by the feedback loop later.
6. For reference kinds: derive separate detection rules for each of the 5 reference kinds (`reference_intra_doc`, `reference_cross_doc`, `reference_spec` with `style=direct` and `style=indirect` as separate sub-rules, `reference_list` section pattern, `reference_list_entry` per-entry pattern). Indirect spec citations have a two-step pipeline path: parser detects `[N]` at source → looks up entry N in the doc's `reference_list_map` → resolver hits the standards graph. The `target` dict on annotations is **ignored for rule derivation** — it's reserved for resolver-eval ground truth.
7. Apply mapping forward-redaction to all output values (per `02-content-safety.md`).
8. **Mapping snapshot** [D-062]. After deriving rules, write a per-bootstrap
   mapping snapshot to `customizations/mappings/<bootstrap_id>.json` so the
   pipeline's substitution layer can resolve placeholders at parse time:
   ```json
   {
     "version": 1,
     "bootstrap_id": "<bootstrap_id>",
     "mappings": {
       "MNO0": "<real value>",
       "MNO0_ALIAS": "<real value>",
       "MNO0_NAME": "<real value>",
       "PLAN0": "<real value>",
       "PLAN1": "<real value>",
       "REL0": "<real value>"
     }
   }
   ```
   Top-level `mappings` keys are placeholder names **without** angle brackets.
   Source the values from `<env_dir>/state/cline-mapping.json` — include only
   the entries this bootstrap's annotations reference (typically the MNO
   short / alias / name set, every PLAN seen, every REL seen). Skip per-`REQID-N`
   entries; the profile uses the generic `<DIGITS>` placeholder for numeric
   suffixes, not specific req IDs. The directory is **not** gitignored — the
   snapshot gets committed and pushed to the company-internal git remote so the
   team shares one canonical mapping; the work-PC pre-push hook (installed by
   `~/work/utils/git-sync/sync-work.sh`) blocks any push to the public mirror
   (`github.com`).

## Output: `BOOTSTRAP` report shape (apply mapping; max 25 lines)

```
BOOTSTRAP v=1 docs=<N> kinds=<M> annotations=<total>
bootstrap_id: bs_<id>                ← placeholdered profile filename
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

- **Maximum 25 lines** in the output report (excluding the `bootstrap_id` line, which is mandatory).
- Do NOT write to `customizations/profiles/bs_<id>.json` — Teacher LLM does that.
  You DO write `customizations/mappings/bs_<id>.json` (owned by Cline; pushed to
  company-internal git, blocked from public github by the pre-push hook) per Step 8.
- Do NOT commit anything to git. Stage 0 of the loop ends with the user typing the
  BOOTSTRAP report into Teacher LLM.
- Apply mapping forward-redaction to every output token. Derived regex strings use
  placeholders directly: specific (`<MNO0>`, `<PLAN0>`, `<REL0>`) for known-fixed
  values, generic (`<MNO>`, `<PLAN>`, `<REL>`, `<DIGITS>`) for wildcards. Examples:
  - `req_id` regex: `<MNO0>_REQ_<PLAN>_<DIGITS>` (anchored on the MNO short prefix
    you've seen in this corpus, generic over plans + digit count). The pipeline's
    substitution layer turns `<MNO0>` into `re.escape(VZ)` and `<PLAN>` into
    `[A-Z0-9_]+` at parse time.
  - `reference_list_section_pattern`: `(?i)^references$|^bibliography$` (text isn't
    proprietary; no placeholders needed).

## What Teacher LLM does next

After reading the BOOTSTRAP report (which includes `bootstrap_id: bs_<id>`), Teacher LLM:
1. Generates the **placeholdered** profile at `customizations/profiles/<bootstrap_id>.json`
   (or updates an existing one keyed to that id) using the derived patterns. Profile
   regex strings carry placeholders verbatim; the public mirror sees no proprietary
   names.
2. Generates parser code for any new `kinds` (e.g., `references_*` if not previously
   handled).
3. Commits + pushes to public github (Teacher LLM's normal flow).

You then `git pull` on the work PC. The substitution layer reads
`customizations/mappings/<bootstrap_id>.json` (which **you** wrote in Step 8 of this
playbook) and resolves placeholders to real values at parse time. Run the parser,
proceed to Phase 4 (humans review via the Parse Review web page) → `feedback-loop.md`.
