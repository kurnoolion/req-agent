---
name: land-strand
description: Land a strand — the terminal event when work shipped. Promotes each entry in decisions-draft.md to canonical DECISIONS.md with the next sequential D-XXX, marks STRAND.md status=landed with today's date, and moves the folder to strands/_archive/. Architect-driven and sequential — never run two land-strands concurrently across clones, because DECISIONS.md numbering must stay collision-free. Propose-don't-write throughout; every promotion is user-approved.
---

## Argument

1. **Name** (required) — the active strand to land. Must exist at `docs/compact/strands/<name>/`. Archived strands cannot be re-landed.

## Procedure

Propose-don't-write throughout. Each promotion and the final move are confirmed by the user before any state changes.

### 1. Validate

- `docs/compact/` must exist (COMPACT project).
- `docs/compact/strands/<name>/STRAND.md` must exist. If only `docs/compact/strands/_archive/<name>/` exists, abort:

  > "Strand `<name>` is already archived (landed on <date>). Landing is terminal — there's nothing to do."

- Read `STRAND.md` and surface to the user: status, opened, assignees, target modules, summary. If status is already `landed` or `abandoned`, abort with a clear message — a partial prior landing should not be silently re-attempted.

### 2. Check team coordination

Because DECISIONS.md numbering is sequential and shared, ask the user to confirm:

> "About to promote draft decisions from strand `<name>` into canonical `DECISIONS.md`. If another teammate might be running `/land-strand` on a different strand right now, coordinate first — concurrent landings can collide on D-XXX numbering. Proceed? (yes / no)"

On `no`, stop. Do not proceed.

### 3. Triage draft decisions

Read `docs/compact/strands/<name>/decisions-draft.md`. If empty or contains only whitespace, skip to **step 5** (no promotions to do, but the strand can still land).

If non-empty, parse the file into individual decision blocks. Drafts follow the same template as canonical DECISIONS entries but may use a placeholder ID like `D-DRAFT-1`, `D-DRAFT-2`, etc.

Present each draft to the user as a numbered list with one-line summaries. For each, ask one of:
- **promote** — proceed to step 4 for this entry
- **edit** — let the user revise the draft inline before promotion
- **drop** — discard without promoting (it goes nowhere — record nothing in canonical DECISIONS.md; if the user wants a note, they can edit STATUS.md Flags manually after landing)
- **defer** — keep the draft in the strand archive (so it survives in `_archive/<name>/decisions-draft.md` for future reference) but do not promote

Carry the user's verdict for each draft into step 4.

### 4. Promote (one entry at a time)

For each draft marked **promote**:

1. Determine the next ID by reading `docs/compact/DECISIONS.md` and finding the highest `D-NNN` value, then add 1. Pad to at least 3 digits (`D-019`, `D-100`).
2. Replace the draft's placeholder ID with the new canonical ID.
3. Stamp the entry's date with today.
4. Add a one-line provenance footer to the entry: `Promoted from strand: <name> on <today>`. This makes the audit trail explicit.
5. Show the final entry to the user for one last approval. On approval, append to `DECISIONS.md`. On rejection, treat as **edit** and loop back.

Process draft entries strictly in order. Do not batch the appends — appending one at a time means the next promotion sees the just-written entry and gets the correct next ID, which matters if the architect aborts midway.

### 5. Update STRAND.md

Edit `docs/compact/strands/<name>/STRAND.md`:
- `Status: in-flight` → `Status: landed`
- `Landed:` → today's date YYYY-MM-DD
- Append a single line at the bottom of the Notes section: `Landed on <date> with <N> promoted decisions: <D-IDs comma-separated>` (or `with 0 promoted decisions` if none).

Show the diff. On approval, write.

### 6. Move to archive

Move `docs/compact/strands/<name>/` to `docs/compact/strands/_archive/<name>/`. Use `git mv` if the strand is git-tracked (so rename history is preserved); plain `mv` otherwise.

Confirm the move succeeded. If the destination already exists (someone reused a slug — see `start-strand` rule 3), the user should have been warned at creation time; abort here with: "Cannot archive: `strands/_archive/<name>/` already exists. Rename or remove the prior archive first."

### 7. Clear the binding if it points here

If `.compact/current-strand` exists and its content equals `<name>`, delete the file (or write empty). Tell the user: "Strand was bound to this session — binding cleared. `close-session` will now write to canonical STATUS.md / DECISIONS.md until you bind another strand."

### 8. Confirm

Tell the user:

> "Landed strand `<name>`. Promoted <N> decisions: <D-IDs>. Archived to `docs/compact/strands/_archive/<name>/`.
>  Notify teammates if they may have local clones with this strand still active — they should `/list-strands` to see it's archived now."

If the strand had `Assignees:` with more than one name, the notify line is the only soft enforcement of team coordination — surface it loudly.

## Rules

- **Never auto-promote.** Every appended `DECISIONS.md` entry is shown and approved one at a time. Promotion is the most permanent action in COMPACT — it modifies the canonical decision log that everything else cites.
- Sequential by design. Do not attempt locking or concurrency control — the step-2 prompt makes coordination the user's responsibility, which fits the "architect-driven" model.
- Landed status is irreversible. There is no `/unland-strand`. If a landing was a mistake, the user can manually `git revert` the commits that captured it.
- The archived strand folder is **read-only history**. Future skills (notably `doctor` and `drift-check`) should never write to anything under `_archive/`.
- If the user runs `/land-strand <name>` on a strand whose `decisions-draft.md` has entries the user wants to discard rather than promote, **drop** is the right verdict — there is no "promote silently". Visibility of the discard decision is intentional.
- Do not delete the `decisions-draft.md` file even after promoting all entries; it stays in `_archive/` as part of the audit trail, with its drafts marked as promoted via the canonical D-IDs.
