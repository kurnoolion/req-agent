# Playbook: derive-rule

**Purpose**: build a detection rule for ONE structural element (strikethrough, TOC,
version history, requirement-ID format, definitions layout, etc.) — produce a `RULE`
report Teacher LLM can use to update the parser/profiler.

**Input**: element name, one of:

- `strikethrough` — line-strike on text (PDF graphic op or font flag)
- `toc` — table-of-contents page detection
- `version-history` — revision-history heading + table
- `req-id` — requirement-ID format
- `defs` — definitions / acronyms section layout
- `applicability` — applicability marker (e.g., LTE / 5G / form-factor tags)
- `priority` — priority marker (mandatory / optional / conditional)

If the element isn't on this list, ask the user before proceeding.

## Steps

1. Read the relevant existing logic:
   - `core/src/parser/MODULE.md` — invariants, key choices
   - `core/src/parser/structural_parser.py` — current detection methods
   - `core/src/profiler/MODULE.md` — what the profiler measures
   - `core/src/profiler/structural_profiler.py` — current detection patterns
2. Sample the corpus for ~10 instances + ~10 NEAR-miss non-instances of the element.
   - For each, note the discriminating signal: regex, font flag, geometric position,
     surrounding context, table/cell layout.
   - Do **NOT** capture verbatim text of any sample.
3. Express the discriminating rule:
   - **Text-shape** → a regex (anchored where appropriate)
   - **Visual** → a geometric heuristic (line count, width threshold, position relative to
     bounding box)
   - **Font** → font-flag check (bold / italic / strikethrough / size threshold)
   - **Combined** → all-of / any-of of the above, with explicit operators
4. Test the rule against the full corpus:
   - Count true-positives (rule fires AND is correct)
   - Count false-positives (rule fires AND is wrong)
   - Count false-negatives (rule should have fired AND didn't)
5. Categorize FPs and FNs by failure mode (max 3 categories each). Use structural names,
   never quoted content. Examples:
   - `deep-nesting`, `merged-section-numbers`, `font-flag-missing`, `inline-strike-only`
6. If a current rule exists for this element, compare delta vs current.

## Output: `RULE` report shape (apply mapping to every token before emitting)

```
RULE v=1 element=<element-name>
def: <rule-as-regex-or-heuristic>
TP: <int>   FP: <int>   FN: <int>
coverage: <TP>/(<TP>+<FN>) = <float>%
fp_modes: <category>=<count>; <category>=<count>; <category>=<count>
fn_modes: <category>=<count>; <category>=<count>
delta: catches=<+/-int> over_baseline   (or "n/a" if new element)
```

## Examples (illustrative, not corpus-specific)

```
RULE v=1 element=strikethrough
def: geom 2-lines height≤2pt width≥0.5*cell_width, AND row-aligned
TP: 487   FP: 12   FN: 16
coverage: 487/503 = 96.8%
fp_modes: row-divider=8; underline=4
fn_modes: single-line-strike=11; partial-cell-strike=5
delta: catches=+33 over_baseline
```

```
RULE v=1 element=toc
def: leaderdots\s+\d+$ on >=70% of page lines
TP: 14   FP: 0   FN: 2
coverage: 14/16 = 87.5%
fp_modes: (none)
fn_modes: wrap-across-pages=2
delta: catches=+5 over_baseline (was thr=0.8, now 0.7)
```

## Constraints

- **Maximum 10 lines** in the output (8 fixed + 2 optional context).
- Categories must be format/structural names, never quoted corpus content.
  Good: `numbered-but-no-space`, `strike-on-table-row`. Bad: any verbatim word from a hit.
- If the rule needs values from the mapping (e.g., MNO prefix in a regex), include them
  as placeholders.
- If the rule needs a PROF report's context to make sense (e.g., "for `<PLAN0>` only"),
  prepend a one-line `for: <PLAN-placeholder>`.

## Common follow-ups Teacher LLM may request after RULE

- "Promote rule to `core/src/parser/structural_parser.py:<method>` — produce a PR" →
  Teacher LLM commits.
- "Update profile-schema field `<field>` to accept the new shape" → Teacher LLM commits.
- "Add a corrections override for the FNs you couldn't fix in code" → Teacher LLM provides a
  YAML / JSON correction template; you fill in the actual req IDs locally and commit
  to `customizations/corrections/`.
