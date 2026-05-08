# Playbook: feedback-loop

**Purpose**: refine detection rules based on human feedback after a parser/profile run.
The Parse Review web page in NORA's UI lets reviewers flag wrong rows (false positives)
and missed rows (false negatives); this playbook reads those flags and produces a
`FEEDBACK` report Teacher LLM can act on.

**When to use this**:
- After the parser ran and humans reviewed output via Parse Review.
- After integration tests caught a regression and humans want a structural fix vs a
  per-req correction.
- After a reviewer marked corrections in `<env_dir>/corrections/<plan>_corrections.csv`
  (or whatever the existing format is).

**Input**: stage name (typically `parse` or `profile`) + which plan/release scope to
review.

## Steps

1. Read the most recent Parse Review output (existing format under `<env_dir>/`):
   - `<env_dir>/reports/audit/<plan>_audit.csv` — HIGH/MEDIUM/LOW with reviewer marks
   - `<env_dir>/corrections/<plan>_corrections.csv` — per-req correction overrides
2. For each correction or flagged row:
   - Identify what the parser produced vs what the reviewer marked correct.
   - Categorize the failure mode (max 3 categories per kind):
     - For section-heading FPs: e.g., `non-heading-bold-text`, `revision-history-row-misclassified`
     - For req_id FNs: e.g., `whitespace-fused`, `letter-after-digits`
     - For strikethrough FPs: e.g., `row-divider-line`, `underline-misread`
     - For TOC FNs: e.g., `wrap-across-pages`
3. Read the current rule for the affected kind (from
   `customizations/profiles/<plan>/profile.json` or the parser source) so you can
   compute the delta the rule update needs to handle.
4. Propose a rule refinement that handles the categorized failure modes without
   regressing existing TPs. Test it locally if possible; otherwise mark as
   `untested-locally`.
5. Apply mapping forward-redaction to all output (per `02-content-safety.md`).

## Output: `FEEDBACK` report shape (apply mapping; max 20 lines)

```
FEEDBACK v=1 stage=<stage> plan=<PLAN-placeholder>
prov: <count-FP> FPs, <count-FN> FNs from Parse Review (audit-csv version=<...>)

<kind>: current_rule_summary
  fp_modes: <category>=<count>; <category>=<count>
  fn_modes: <category>=<count>; <category>=<count>
  proposed: <updated-rule-or-fragment>
  delta: catches=<+N> drops=<-N>; tested=<yes|no|local-only>

<kind>: ...

errors: (none or "untested-locally: <kind>")

ASK: <specific deliverable Teacher LLM should commit, ≤20 words>
```

If multiple kinds got feedback in this round, list each. Cap at 3 kinds per FEEDBACK
report — if more, run multiple FEEDBACK loops separately so each fits in the user's
typing budget.

## Example

```
FEEDBACK v=1 stage=parse plan=<PLAN0>
prov: 8 FPs, 12 FNs from Parse Review (audit-csv v=2)
mapping: v=1 entries=12

section_heading: ^(\d+(?:\.\d+)+)\s+\S
  fp_modes: revision-history-row=4; phantom-depth1-from-block-wrap=4
  fn_modes: nospace-after-number=8; merged-section-numbers=2; deep-nest-d≥9=2
  proposed: ^(?:(\d+)(?=\s)|(\d+(?:\.\d+)+)(?=\s|[A-Z]))
  delta: catches=+10 drops=-7; tested=local-only

ASK: tighten sec_re in customizations/profiles/<PLAN0>/profile.json per "proposed".
     Add integration test pair for "merged-section-numbers" case.
```

## Constraints

- **Maximum 20 lines** in the output.
- **Maximum 3 kinds per report** — split if more.
- Categorize failure modes by **structural / format names** only, never quoted content.
- If the proposed rule update needs values from the mapping (MNO prefix in regex etc),
  emit them as placeholders.
- Do NOT modify `customizations/profiles/` directly — Teacher LLM does that.
- Do NOT commit to git.

## What Teacher LLM does next

After reading the FEEDBACK report, Teacher LLM:
1. Updates the rule in `customizations/profiles/<plan>/profile.json` (regex tightening,
   threshold change) OR in the parser source if it's a structural code change.
2. Adds an integration test case for the categorized failure mode (so future runs catch
   regressions of this fix).
3. Commits to git.

You `git pull`, re-run the parser, run Parse Review again, and either close the loop
(coverage acceptable) or run another FEEDBACK iteration (further refinements).

## Stages where this loop applies

| Stage | Feedback channel | Notes |
|---|---|---|
| `parse` | Parse Review web page | most common driver |
| `profile` | Parse Review (drives both since profile feeds parse) | usually paired with parse feedback |
| `resolve` | Resolve Review web page | for cross-reference resolution |
| `eval` | Eval result review | tighter loop, drives synthesis-side changes |

`extract`, `taxonomy`, `standards`, `graph`, `vectorstore` don't typically use this
playbook — their corrections go through different channels (extraction is mechanical;
taxonomy/standards/graph are derived; vectorstore is rebuild-only).
