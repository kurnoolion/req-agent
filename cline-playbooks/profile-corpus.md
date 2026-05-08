# Playbook: profile-corpus

**Purpose**: profile one document — extract format patterns (heading shape, req-ID format,
TOC, strikethrough, version-history, definitions layout) — produce a `PROF` report Teacher LLM
can act on without seeing corpus content.

**Input**: a document path under `<env_dir>/input/<MNO>/<RELEASE>/<PLAN>.{pdf,docx,xlsx}`.

## Steps

1. Identify MNO / RELEASE / PLAN from the path. If any aren't already in the redaction
   mapping, run `cline-playbooks/mapping.md` to add them BEFORE producing the report.
2. Run the profiler:
   ```
   python -m core.src.profiler.profile_debug --create --doc <path>
   ```
   This produces `<env_dir>/out/profile/<plan>_profile.json`.
3. Read the produced profile:
   - `heading_detection.numbering_pattern` (regex)
   - `requirement_id.pattern` (regex)
   - `toc_detection_pattern` + `toc_page_threshold`
   - `strikethrough_detection` method + parameters
   - `revision_history_heading_pattern`
   - `definitions_extraction.layout` (paragraph / table-2col / etc.)
4. Run the parser using this profile:
   ```
   python -m core.src.parser.parser_cli \
     --doc <path> \
     --profile <env_dir>/out/profile/<plan>_profile.json \
     --tree-out <env_dir>/out/parse/<plan>_tree.json
   ```
5. Run parse-audit:
   ```
   python -m core.src.parser.parse_review --create-all
   ```
   This populates `<env_dir>/reports/audit/<plan>_audit.csv` with HI/MED/LOW
   classifications per requirement.
6. Read the audit CSV; aggregate by severity. Note category of any LOW rows by
   structural pattern (e.g., `deep-nesting`, `merged-section-numbers`) — never by quoted
   content.

## Output: `PROF` report shape (apply mapping to every token before emitting)

```
PROF v=1 doc=<PLAN-placeholder>
sec_re:    <regex>                   ← from profile.json, generic
req_re:    <regex with placeholders> ← e.g., ^<MNO0>_REQ_<PLAN0>_\d+$
toc:       <pattern> thr=<float>     ← e.g., leader-dot-page thr=0.7
strk:      <method> [<params>]       ← e.g., geom 2lines width≥0.5
ver:       <regex>                   ← e.g., ^revision\s+history$
defs:      <layout>                  ← e.g., 2col-table Acronym|Definition
N:         req=<int> sec=<int> tbl=<int> fig=<int>
audit:     HI=<float>% MED=<float>% LOW=<float>%
miss:      <count> in <severity> [+ structural-category]
notes:     <≤20-word abstract observation, optional>
```

If any new structural element was observed (not previously in the profile schema), add a
`new:` line:

```
new: <element-name> <one-line abstract description>
```

## Constraints

- **Maximum 15 lines** in the output (12 fixed + up to 3 conditional).
- Apply mapping to every token. Real plan IDs, MNO names, file paths, req IDs must all be
  redacted.
- Regex patterns: emit verbatim if they are already generic (numbering shapes, position
  rules). If a regex contains a real MNO/PLAN literal, redact those literals to placeholders.
- If a `MAPPING:` line was added during this run, prepend it to the report.

## Common follow-ups Teacher LLM may request after PROF

- "Tighten `sec_re` to handle X case (deep nesting, merged numbers)" → Teacher LLM commits a
  regex change to `customizations/profiles/<PLAN>/profile.json`.
- "Lower `toc.thr` to 0.6 for this plan" → similar.
- "Add `revision_history_heading_pattern` for this plan" → similar.

You apply via `git pull` + re-run profile-corpus.
