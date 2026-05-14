## 2026-05-16 — seeded from STATUS.md at adopt-strands

- **Glossary scoring still needed** — revhist now has a signal-based detection path; glossary still relies solely on `definitions_section_pattern` matching a section title. Work-PC corpus shows 135/135 missing glossary because the section title isn't matched. Build a parallel `GlossaryDetection` (same scoring shape: heading-text match + vocab + cell-fingerprint for col-0 short-uppercase-tokens / col-1 prose) — should drop the 135 substantially.

- **Glossary signal-based detection** (carry from In Progress) — parallel `GlossaryDetection` profile field; same shape as `RevhistDetection`.

## 2026-05-16 — bound and idle; section-handling bug shipped via sibling strand

### Done this session
- Nothing on glossary-scoring directly — bound late in the session after the `section-handling` strand landed.

### In progress
- Build the `GlossaryDetection` profile dataclass mirroring `RevhistDetection`'s three-signal shape. `RevhistDetection` (D-073, `core/src/profiler/profile_schema.py`) is the working template; lift the structure and substitute glossary-tuned defaults:
  - **Heading-text signal**: matches `definitions_section_pattern` already.
  - **Vocab signal**: tokens like `acronym`, `acronyms`, `abbrev`, `abbreviation`, `definition`, `definitions`, `term`, `terms`, `expansion`, `meaning`. Scan headers + merged-cell text + body cells (same as revhist's body-cell extension on commit `a8ed9cf`).
  - **Cell-fingerprint signal**: col-0 short uppercase tokens (`^[A-Z][A-Z0-9_-]{1,15}$`), col-1 non-empty prose. Different shape from revhist's version/date fingerprint.
  - **Position signal**: glossaries are NOT typically front-matter — they're usually in an Acronyms / Definitions chapter mid-doc, or at end. Likely drop the position signal entirely (weight = 0) or invert it (back-half of doc preferred).

### Next
- Decision: drop position signal vs. invert it. Worth a draft decision when implementation starts — `RevhistDetection`'s position default of 0.30 doesn't translate.
- Sibling parser change: extend `_extract_definitions` to also run the score path when `definitions_section_pattern` + `definitions_table_header_pattern` both miss. Same cascade shape as revhist.
- Surface per-signal breakdown on the Summary tab's glossary evidence panel (mirrors `RevhistMatch.score_breakdown` from D-073).
- Wire `parse_debug` glossary subcommand (or extend `revhist` to take a `--kind glossary` arg).

### Flags
- Untracked working-tree state from today: strand folders + STATUS banner + `.gitignore` entry. Not committed yet; will commit at end of close-session.
