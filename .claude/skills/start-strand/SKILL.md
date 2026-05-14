---
name: start-strand
description: Create a new strand — a folder of in-flight state (STRAND.md + journal.md + decisions-draft.md) under docs/compact/strands/<name>/. Strands hold the running narrative for one chunk of parallel work; sessions bind to them with switch-strand. Interviews the user for summary / target modules / assignees, scaffolds the folder, and ensures .compact/ is gitignored. Does not bind the session — call /switch-strand after.
---

## Argument

1. **Name** (required) — kebab-case slug for the strand. Pattern: `^[a-z][a-z0-9-]{1,40}$`. Used as the directory name under `docs/compact/strands/`. Choose a name that reads well in `/switch-strand <name>` and `/land-strand <name>`. Examples: `llm-upgrade`, `pipeline-refactor`, `qa-feedback-loop`.

## Procedure

1. **Validate the name.** If the argument doesn't match the kebab-case pattern, or equals the reserved literal `_archive`, abort with a one-line message and a corrected suggestion if obvious.

2. **Verify this is a COMPACT-equipped project.** `docs/compact/` must exist. If not, abort:

   > "No `docs/compact/` directory — this project doesn't appear to be COMPACT-equipped. Run `/project-init` or `/project-init --retrofit` first."

3. **Check for conflicts.**
   - If `docs/compact/strands/<name>/` already exists: surface its current STRAND.md status and stop. Suggest `/switch-strand <name>` to bind, or pick a different name.
   - If `docs/compact/strands/_archive/<name>/` exists (a landed/abandoned strand with the same slug): warn that the name has been used before, show the archived strand's status + landed/abandoned date, ask the user to confirm reuse or pick a fresh name. Reusing is allowed but confusing in history.

4. **Ensure parent directories exist.** Create `docs/compact/strands/` and `docs/compact/strands/_archive/` if missing. The `_archive/` directory exists from day 1 so `/land-strand` doesn't have to special-case its creation.

5. **Ensure `.compact/` is gitignored.** The session-binding marker (`.compact/current-strand`) is per-clone, never shared.
   - If `.gitignore` exists at the repo root and contains a line that covers `.compact/` (exact match `.compact/` or `.compact`), do nothing.
   - Otherwise append a one-line block to `.gitignore`:
     ```
     # COMPACT per-clone session binding (do not commit)
     .compact/
     ```
   - If `.gitignore` doesn't exist at the repo root, create it with the same block.

6. **Interview the user.** Ask three short questions, plain prose, no forms. Treat answers as authoritative; do not infer.

   - *"One-paragraph summary — what is this strand for?"* — captured into STRAND.md Summary section. Required (cannot be empty).
   - *"Target modules — comma-separated list of modules you expect to touch, or empty if you don't know yet."* — captured into the `target modules:` field. Empty is a valid answer.
   - *"Assignees — who's on this strand? Default: <value of `git config user.name`>."* — captured into the `assignees:` field. Free-form; commas separate multiple. Accept the default if the user just presses enter.

7. **Generate `STRAND.md`** at `docs/compact/strands/<name>/STRAND.md` from this template, filling in answers:

   ```markdown
   # <strand-name>

   **Status:** in-flight
   **Opened:** <today's date YYYY-MM-DD>
   **Landed:**
   **Assignees:** <interview answer>
   **Target modules:** <interview answer, or `unspecified` if empty>
   **Active phase:**

   ## Summary

   <interview answer>

   ## Notes

   <empty — appended to over the strand's lifetime>
   ```

   `Status` starts at `in-flight`. The `planning` status is also valid but rarely used — prefer to enter `in-flight` and journal early thinking. `Landed` and `Active phase` are blank at start.

8. **Create empty companion files.**
   - `docs/compact/strands/<name>/journal.md` — empty file. `close-session` will start appending to it once a session binds.
   - `docs/compact/strands/<name>/decisions-draft.md` — empty file. `close-session` will append draft decisions here when a session is bound; `land-strand` promotes them to canonical `DECISIONS.md` at landing time.

9. **Confirm.** Tell the user:

   > "Created strand `<name>` at `docs/compact/strands/<name>/`.
   >  Bind this session to it with `/switch-strand <name>`."

   Do not auto-bind. The user may want to start the strand and continue current work, binding later.

## Rules

- Do not modify `STATUS.md`, `DECISIONS.md`, `MODULE.md`, `MAP.md`, or any code. Creating a strand is a no-op against the canonical state.
- Never auto-bind the session. `/switch-strand` is the binding action; keeping it separate makes the lifecycle explicit.
- Do not invent values during the interview. If the user gives an empty Summary, re-ask once and then abort if still empty — a strand without a summary is dead weight in `list-strands`.
- The `target modules` field is intent, not contract. It is allowed to drift as the strand learns its scope; `switch-phase` can offer to add to the list when used inside a bound session.
- `Assignees` is informational. It is not enforced by any other skill; reassignment is just editing the line.
