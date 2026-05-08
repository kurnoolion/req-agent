# Playbook: share-back

**Purpose**: bundle multiple reports (some combination of ORIENT / PROF / RULE / RPT) into
a single hand-typeable blob the user can deliver to Teacher LLM in one trip.

**Input**: which reports the user wants bundled (typically the most recent N from this
session) plus a one-line context describing the goal.

## Steps

1. Identify the reports to bundle. If unspecified, default to: the most recent ORIENT
   (or skip if Teacher LLM has already been oriented this session) + the most recent
   PROF / RULE / RPT.
2. Concatenate, blank line between each.
3. Add a top-level `BUNDLE` header line + a 1–2 line `context:` block.
4. Add an `ASK:` block at the end naming what Teacher LLM should produce next (1–2 lines —
   concrete deliverable, not vague).
5. Verify total is ≤40 lines. If exceeded, drop the lowest-priority report (priority:
   ORIENT < PROF < RULE < RPT; drop ORIENT first, RPT last).
6. Apply mapping forward-redaction one final time to the entire bundle (in case any
   sub-report was emitted earlier without redaction).

## Output: `BUNDLE` report shape

```
BUNDLE v=1 reports=<count>
context: <one-line summary of why this bundle, what task triggered it>
mapping: v=<N> entries=<N>

<sub-report 1, with its leading-line type marker>

<sub-report 2>

...

ASK: <what Teacher LLM should generate next, 1-2 lines>
```

## Example

```
BUNDLE v=1 reports=2
context: Strikethrough rule misses partial-cell strikes on <PLAN2>; want updated geom heuristic
mapping: v=1 entries=12

PROF v=1 doc=<PLAN2>
sec_re:    ^(\d+(?:\.\d+)+)\s+\S
req_re:    ^<MNO0>_REQ_<PLAN2>_\d+$
toc:       leader-dot-page thr=0.7
strk:      geom 2lines width≥0.5
ver:       ^revision\s+history$
defs:      2col-table Acronym|Definition
N:         req=794 sec=494 tbl=178 fig=42
audit:     HI=94.2% MED=5.1% LOW=0.7%
miss:      24 LOW (partial-cell-strike + deep-nest)

RULE v=1 element=strikethrough
def: geom 2-lines height≤2pt width≥0.5*cell_width, AND row-aligned
TP: 487   FP: 12   FN: 16
coverage: 487/503 = 96.8%
fp_modes: row-divider=8; underline=4
fn_modes: single-line-strike=11; partial-cell-strike=5
delta: catches=+33 over_baseline

ASK: Update strikethrough rule in core/src/extraction/pdf_extractor.py to also catch
partial-cell strike (line covers ≥30% of cell width OR cell height ≥1 line).
```

## Constraints

- **Maximum 40 lines** total. If truncated, append `BUNDLE_TRUNCATED: dropped <type>`
  as a final line.
- ASK line is concrete — name a specific deliverable (file path + change description),
  not a vague "fix this".
- Never include the same report twice (dedup by report-type marker).
- Apply mapping forward-redaction once over the final bundle, not just per-sub-report,
  in case a placeholder reference was missed.

## Common ASK shapes

- "Update regex `<field>` in `customizations/profiles/<PLAN>/profile.json` to handle
  category `<X>`."
- "Promote rule `<element>` from playbook output to
  `core/src/parser/<file>:<method>`; produce PR."
- "Add a corrections-file template for the FN cases categorized as `<category>`."
- "Wire `<knob>` through the resolver chain so it can be tuned via `/config` page."
- "Run an A/B comparison: with and without grouping enabled; report deltas."
