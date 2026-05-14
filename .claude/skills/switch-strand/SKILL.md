---
name: switch-strand
description: Bind the current session to a strand. Writes the strand name to .compact/current-strand so close-session and switch-phase route writes to the strand instead of canonical state files. Read-only on the canonical layer. Pass `none` or `--clear` to unbind and revert to legacy (STATUS.md / DECISIONS.md) writes.
---

## Argument

1. **Name** (required) — either:
   - an existing strand name (the slug under `docs/compact/strands/<name>/`), **or**
   - the literal `none` or `--clear` to unbind this session.

## Procedure

Every step is **idempotent**. If the requested binding is already in effect and the strand's `STRAND.md` is unchanged since this session last read it, treat as a no-op and re-surface the current state.

1. **Verify this is a COMPACT-equipped project.** `docs/compact/` must exist. If not, abort with the same message as `start-strand`.

2. **Handle the unbind shortcut.** If the argument is `none` or `--clear`:
   - If `.compact/current-strand` exists, delete it (or write an empty line — both are equivalent; deletion is cleaner).
   - Confirm: "Strand unbound. `close-session` will write to canonical STATUS.md / DECISIONS.md." Stop here.

3. **Locate the strand.**
   - Look in `docs/compact/strands/<name>/`. If it exists, proceed.
   - If not found, also check `docs/compact/strands/_archive/<name>/`. If found there, tell the user:

     > "Strand `<name>` is archived (status: <landed|abandoned>, on <date>). Archived strands cannot be bound — their journals are immutable history. To start a fresh strand with the same focus, run `/start-strand <new-name>`. To just read the archived narrative, open `docs/compact/strands/_archive/<name>/journal.md` directly."

     Stop here. Do not bind.
   - If not found in either location, suggest `/list-strands` to see what's available and `/start-strand <name>` to create a new one. Stop here.

4. **Read `STRAND.md`.** Surface to the user, compactly:
   - Status, Opened, Assignees, Target modules, Active phase
   - Summary (first paragraph)

   If `STRAND.md` is malformed (missing frontmatter fields), warn but still bind — let `doctor` surface the structural problem.

5. **Read recent journal entries.** If `journal.md` exists and is non-empty, surface the **last 1–2 entries** (most recent first) so the user can pick up where they left off. If empty, note "Journal empty — no prior sessions on this strand."

   Do not load the entire journal. The tail is what's load-bearing for resuming.

6. **Write the binding.**
   - Ensure `.compact/` directory exists at the repo root. Create if missing.
   - Write the strand name (single line, trailing newline) to `.compact/current-strand`. Overwrite if a previous binding existed.
   - If `.gitignore` doesn't cover `.compact/`, append the one-line block (same as `start-strand` step 5) — self-heal for clones that pre-date the strand scaffolding.

7. **Confirm.** Tell the user:

   > "Bound to strand `<name>`. Status: <status>. Target modules: <list or 'unspecified'>.
   >  Active phase: <phase or 'unset — use /switch-phase'>.
   >  `close-session` will journal here; draft decisions go to this strand's `decisions-draft.md`."

   If the previous binding was a different strand, prefix with: "Switched from `<previous>` → `<name>`."

## Rules

- This skill never modifies `docs/compact/strands/<name>/STRAND.md`, `journal.md`, `decisions-draft.md`, or anything under `docs/compact/`. Binding is a session marker only.
- Never auto-create a strand. If the named strand doesn't exist, the user must explicitly `/start-strand <name>` — silent creation would invent state the user didn't intend.
- Archived strands are read-only by design: they represent committed history, and re-opening one to add to its journal would break the audit trail. If the user wants to revisit the same focus, a new strand is the correct primitive.
- The binding lives at `.compact/current-strand` (gitignored, per-clone). Other clones / teammates have their own bindings. This is by design — multiple devs can be in different strands at the same time on the same repo.
- After binding, immediately tell the user how `close-session` will behave. The whole point of binding is to redirect end-of-session writes; surfacing that contract makes the redirect non-surprising.
