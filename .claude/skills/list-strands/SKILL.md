---
name: list-strands
description: List active strands in the project. Reads STRAND.md frontmatter for each directory under docs/compact/strands/ and prints a table — status, assignees, target modules, last activity. Highlights the currently-bound strand. Pass `--include-archived` (or `--all`) to also show landed/abandoned strands from strands/_archive/. Read-only.
---

## Argument

1. **Flag** (optional): `--include-archived` or `--all` to include the contents of `docs/compact/strands/_archive/` in the output. Omitted: show active strands only.

## Procedure

1. **Verify the project is set up for strands.** `docs/compact/strands/` must exist. If not, print:

   > "No strands directory found. Run `/start-strand <name>` for a new strand, or `/adopt-strands` to retrofit an existing COMPACT project."

   Stop here.

2. **Read the current binding.** If `.compact/current-strand` exists and contains a non-empty line, capture that name as `BOUND`. Otherwise `BOUND` is empty.

3. **Enumerate active strands.** For each subdirectory of `docs/compact/strands/` (except `_archive`):
   - Read its `STRAND.md` if present. If missing or malformed, record it as `[orphan]` for the row and move on (do not skip — `list-strands` is the place these become visible so `doctor` and the user can fix them).
   - Parse the frontmatter-style fields from the top of `STRAND.md`: **Status**, **Opened**, **Assignees**, **Target modules**, **Active phase**.
   - Compute **Last activity**:
     - If `journal.md` is non-empty, use its mtime.
     - Else if `decisions-draft.md` is non-empty, use its mtime.
     - Else fall back to `STRAND.md`'s mtime.
     - Render as relative-time (`2 days ago`, `1 week ago`, `today`).

4. **Enumerate archived strands** (only if `--include-archived` / `--all` was passed). For each subdirectory of `docs/compact/strands/_archive/`:
   - Read its `STRAND.md` for **Status** (landed | abandoned), **Landed** date (or final-update date), **Assignees**, **Target modules**.
   - Do not compute relative-time — show the **Landed** date directly.

5. **Sort.**
   - Active list: bound strand first (if any), then by status priority (`in-flight` > `blocked` > `planning`), then by Last activity descending.
   - Archived list: by Landed date descending (most recently landed first).

6. **Print.** Format as a compact monospace table. Use `★` to mark the bound strand. Truncate long Target modules / Assignees with `…` to keep rows on one line. Example output:

   ```
   Active strands (3):
     ★ llm-upgrade        in-flight  2026-04-15  Mohan,Sasi    extraction,vectorstore   2d ago
       pipeline-refactor  in-flight  2026-04-20  Mohan         parser,resolver          5d ago
       qa-loop            planning   2026-05-01  Sasi          —                        1w ago

   Bound: llm-upgrade  (use `/switch-strand none` to unbind)
   ```

   When `--include-archived` is set, follow with an `Archived strands (N):` block under the active list.

   If there are zero active strands, say so explicitly: "No active strands. (Use `--include-archived` to see archived.)" Do not print an empty table.

7. **Footer hints.** After the table, print a short one-line legend:

   > "Switch into one: `/switch-strand <name>`  ·  start a new one: `/start-strand <name>`  ·  land one: `/land-strand <name>`."

   Only show the relevant hints. If the user is already bound to a strand, lead with the unbind suggestion instead.

## Rules

- Read-only. Touches no files under `docs/compact/` or anywhere else. No side effects beyond stdout.
- If `STRAND.md` is missing or unparseable for a strand, list the row as `[orphan: <dirname>]` rather than skipping it. Hiding orphans defeats the discoverability purpose of this skill.
- The bound strand is highlighted but its position in the table is determined by sort rules — don't always pin it to the top regardless of activity.
- Relative-time strings use coarse buckets (`today`, `Nd ago`, `Nw ago`, `Nmo ago`). The exact day-precision belongs in the journal, not here.
- When the bound strand is archived (a rare edge case, possible if someone landed it from another clone), surface that loudly: `★ llm-upgrade  [BINDING POINTS AT ARCHIVED STRAND]` — and tell the user to `/switch-strand none` or `/switch-strand <other>`.
