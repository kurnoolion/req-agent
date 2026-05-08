# Output discipline: compact, hand-typeable reports

The user reads your report off your screen and **hand-types** the redacted version into
Teacher LLM. Reports MUST be short, structured, and easy to read off a single screen.

## Constraints

- **Maximum 30 lines** per report (target 15)
- **Tabular over prose** wherever possible
- **One observation per line**
- **Fixed format per playbook** — each playbook below defines its report shape exactly
- **Numbers, not adjectives** — `89%` not `most`; `503` not `many`

## Standard report types

Each playbook produces one of these:

| Type | Used by | Lines | Shape |
|---|---|---|---|
| `ORIENT` | orient | 5–8 | session-bootstrap confirmation |
| `MAP` | mapping | 2–4 | mapping diff confirmation |
| `PROF` | profile-corpus | 12–15 | per-element profile summary |
| `RULE` | derive-rule | 8–10 | rule definition + coverage |
| `RPT` | debug-pipeline | 15–25 | per-stage runtime stats |
| `BUNDLE` | share-back | ≤40 | aggregation of multiple reports |

The exact field set per type is defined in the corresponding playbook.

## Conventions

- **Leading line is the report-type marker**: `PROF v=1 doc=<PLAN0>` — first token names
  the type so the user (and Teacher LLM) can parse instantly.
- **Field=value pairs**: `req=487 sec=312 tbl=98` — shorter than prose, no ambiguity.
- **Placeholders only** for any redacted token: never emit a real value.
- **No prose conclusions**: don't write "this looks problematic" or "I recommend X" —
  Teacher LLM interprets and decides.
- **Emit `MAPPING:` lines inline** when you add a new entry to the redaction mapping
  during this report: `MAPPING: added LTEAT→<PLAN0>` (one line per addition).

## What NOT to include

- Prose explanations of "what this means"
- Speculation, interpretation, recommendations
- Full file contents (paths only)
- Any token in unredacted form
- Per-instance breakdowns (aggregate by category, never list verbatim instances)
- Long examples — if the user needs an example, they can ask for one specific one

## Example layouts

**PROF** (good):
```
PROF v=1 doc=<PLAN0>
sec_re:    ^(\d+(?:\.\d+)+)\s+\S
req_re:    ^<MNO0>_REQ_<PLAN0>_\d+$
toc:       leader-dot-page thr=0.7
strk:      geom 2lines width≥0.5
ver:       ^revision\s+history$
defs:      2col-table Acronym|Definition
N:         req=487 sec=312 tbl=98 fig=23
audit:     HI=96.0% MED=3.0% LOW=0.1%
miss:      5 LOW (deep-nest depth≥9)
```

**PROF** (bad — leaks content):
```
PROF v=1 doc=LTEAT
The first section is "1.1 INTRODUCTION" which contains the boilerplate...
Section 1.2 "ATTACH PROCEDURES" describes...   ← verbatim heading text
```
