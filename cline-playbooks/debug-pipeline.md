# Playbook: debug-pipeline

**Purpose**: run one or more pipeline stages, capture per-stage statistics, surface drift
from expected counts and error codes — produce an `RPT` report.

**Input**: stage range (e.g., `extract..parse`, `vectorstore`, or `eval` for a focused
eval-only run). Plus optionally an env_dir override.

## Steps

1. Run the pipeline:
   ```
   python -m core.src.pipeline.run_cli \
     --env-dir <path> \
     --start <start-stage> \
     --end <end-stage> \
     --verbose
   ```
   NORA's stages: `extract`, `profile`, `parse`, `resolve`, `taxonomy`, `standards`,
   `graph`, `vectorstore`, `eval`.
2. Capture each stage's RPT line from stdout. NORA emits these natively:
   ```
   extract: docs=5 blocks=12384 strk=1006 elapsed=42.1s
   parse:   reqs=957 sec=312 toc=140 ver=18 cas=27 defs=158 elapsed=11.3s
   ```
3. If `<env_dir>/state/nora_metrics.db` is readable, pull pipeline-category stats since
   the run started — supplement the RPT lines.
4. If `eval` was in the range, read `<env_dir>/eval/results.json` for the run's summary:
   - `avg_overall_score`
   - `avg_accuracy_score`
   - `avg_citation_quality`
   - per-category accuracy
5. If a prior RPT exists for this env in `<env_dir>/reports/`, compute deltas (current vs
   prior) for the salient counters.
6. If error codes appeared (`PIP-Eddd`, `EXT-Eddd`, `PARSE-Eddd`, etc.), tally counts by
   code; do NOT include error message bodies.

## Output: `RPT` report shape (apply mapping to every token)

```
RPT v=1 env=<placeholder> stages=<start>..<end>
<stage>: <metric>=<value> <metric>=<value> ...
<stage>: ...
errors: <CODE>:<count>; <CODE>:<count>
delta:  <metric>=<+/-int> vs prior; <metric>=<+/-int> vs prior
eval:   overall=<float>% accuracy=<float>% citation=<float>%
        cat: <cat>=<float>%; <cat>=<float>%; ...        (only if eval ran)
notes:  <≤20-word abstract observation, optional>
```

## Example (illustrative)

```
RPT v=1 env=<env_dir> stages=extract..eval
extract: docs=5 blocks=12384 strk=1006 elapsed=42.1s
profile: profiles=5 elapsed=8.4s
parse:   reqs=957 sec=312 toc=140 ver=18 cas=27 defs=158 elapsed=11.3s
resolve: xrefs_internal=842 xrefs_external_plans=37 elapsed=2.1s
taxonomy: features=35 maps_to=12673 elapsed=89s
standards: specs=54 elapsed=120s
graph:   nodes=1290 edges=12673 elapsed=4.2s
vectorstore: chunks=971 elapsed=70s
eval:    overall=88.3% accuracy=64.3% citation=88.9%
         cat: feature=100; single_doc=80.6; trace=83.3; std_cmp=83.3; xdoc=55.0
errors:  (none)
delta:   reqs=+0 chunks=+8 vs prior_run
```

## Constraints

- **Maximum 25 lines** in the output. If more stages were run than fit, drop the lowest-
  variance stage first (e.g., `standards` if its counts are stable across runs).
- Apply mapping to all paths and identifiers.
- For error codes, list code + count only. Never the body.
- For per-category eval breakdown: only include categories whose accuracy is below 90%
  AND has changed from prior run by ≥3pp. Mention the others as `cat_others=stable`.

## Common follow-ups Teacher LLM may request after RPT

- "Re-run with `--continue-on-error` and report which stages errored" → another RPT.
- "Run with `enable_grouping=true` and report whether disambiguation triggered" →
  another RPT plus a `[Stage 4.7]` log capture.
- "Pull a parse-audit summary for the LOW rows" → `parse_review --create-all` then
  follow-up RULE or PROF.
