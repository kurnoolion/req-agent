---
name: adopt-strands
description: Retrofit an existing COMPACT project to use strands. One-time scaffold of docs/compact/strands/ + _archive/; interviews the user to seed 0-N strands from current in-flight work surfaced in STATUS.md; optionally copies recent STATUS entries into the seed strands' journals; stamps a cutover banner in STATUS.md so it becomes the historical record; ensures .compact/ is gitignored. Idempotent guard — refuses to re-run if strands/ already has active content.
---

## Procedure

### 1. Pre-flight

- Verify `docs/compact/` exists. If not: abort, point at `/project-init --retrofit`.
- Verify `docs/compact/STATUS.md` exists. If not: abort with a note that STATUS.md is the starting point this skill reads from; the project needs at least the basic scaffold first.
- Verify adoption hasn't already happened:
  - If `docs/compact/strands/` exists **and** contains at least one non-`_archive` subdirectory, abort: "Strands already adopted — `docs/compact/strands/<N>/` directories present. Use `/start-strand` for new work, `/list-strands` to see existing."
  - If `docs/compact/strands/` exists but is empty (just `_archive/` and nothing else), treat as a half-finished previous adoption and continue.

### 2. Read the landscape

- Read `docs/compact/STATUS.md` in full.
- Read the last ~20 commit messages (`git log --oneline -n 20`) for additional context on what's recently in flight.
- Identify candidate in-flight items. Use these signals:
  - STATUS.md `## In progress` section entries
  - STATUS.md `## Flags` entries (unresolved items often map to strand-worthy work)
  - Recent commits that look mid-feature (e.g., `wip:`, `partial:`, multi-commit feature with no `feat:` cap)
  - Sections of recent journal-style entries clustered around a theme

  Group related signals into candidate clusters. Two STATUS entries about "extraction rewrite" + three commits touching `src/extraction/` form one candidate; an unrelated "logging cleanup" Flag is a separate candidate.

### 3. Present candidates and interview

Show the user a numbered list of candidates with a one-line summary each. Then ask:

> "These look like in-flight work items that could each become a strand. For each, mark: **seed** (create a strand and pre-fill summary + journal from the STATUS context) / **skip** (leave for now, you can `/start-strand` later when needed) / **merge with #N** (combine into the same strand as candidate N). Anything I missed? You can add fresh strand names too."

For each `seed` (and each user-added strand), follow up with:
- Confirm or rename the proposed slug (must match `start-strand`'s kebab-case rule).
- Confirm or edit the proposed one-paragraph summary.
- Confirm or edit the proposed `target modules` list (inferred from commit paths or STATUS module mentions).
- Default `assignees:` to `git config user.name`; let the user override.

Allow the user to seed **zero** strands. Adoption with no seed is a valid choice — they may want the scaffolding ready without yet committing any specific work to it.

### 4. Scaffold

For each strand to be seeded, do exactly what `start-strand` does (rules 4–8 of that skill), with one addition:

- After creating `journal.md`, if the candidate had matching STATUS.md entries, append them to the journal as the first entry, prefixed with a header line:

  ```
  ## <today's date> — seeded from STATUS.md at adopt-strands

  <copied STATUS context, verbatim>
  ```

  Do not transform the copied text. Verbatim preservation makes the seeding auditable.

Always ensure `docs/compact/strands/_archive/` exists even if no strands are seeded (so future `/land-strand` runs have a destination).

### 5. Stamp STATUS.md

Insert a banner near the top of `docs/compact/STATUS.md`, immediately below the file's main heading (or at the very top if there's no heading):

```markdown
> **Strands active from <today's date>.** Mid-session journal entries land in `docs/compact/strands/<name>/journal.md`. Content below this line is historical and is no longer updated by `close-session` when a strand is bound. Architect-only writes (project-wide status, decisions promoted via `/land-strand`) continue to land here.
```

Show the diff. Wait for user approval before writing.

### 6. Ensure `.compact/` is gitignored

Same logic as `start-strand` step 5. Append a one-line block to `.gitignore`:

```
# COMPACT per-clone session binding (do not commit)
.compact/
```

If `.gitignore` doesn't exist, create it with that block. If a covering line is already present, do nothing.

### 7. Confirm

Tell the user:

> "Adopted strands. Seeded <N>: <names>.
>  Run `/switch-strand <name>` to bind this session, or `/list-strands` to see them all."

If `N == 0`:

> "Adopted strands scaffolding (no seeds). Run `/start-strand <name>` when you're ready to track in-flight work."

### 8. Suggest next moves

Add a short note about what changes:

> "From now on:
>  - `/close-session` will write to the bound strand's journal (not STATUS.md) when a strand is bound.
>  - Draft decisions during a strand session go to `decisions-draft.md`; `/land-strand` promotes them to canonical `DECISIONS.md` at shipping time.
>  - Architect / project-wide updates still go to STATUS.md and DECISIONS.md directly (don't bind a strand for those)."

## Rules

- **One-shot.** Never re-run a successful adoption. The guard in step 1 prevents re-scaffolding; the cutover banner in STATUS.md is the visible signal that this already happened.
- **Verbatim seeding.** When copying STATUS context into a seed strand's journal, do not paraphrase, summarize, or "improve" the text. The whole value of the seed is faithful continuity.
- **Never delete or rewrite historical STATUS content.** The banner only annotates; it doesn't excise anything below it.
- Do not auto-bind any strand. Adoption sets up the scaffolding; binding is a deliberate per-session action via `/switch-strand`.
- If the user seeds zero strands, still write the banner and create `strands/_archive/`. The whole-project posture toward strands changes even when no specific item is seeded.
- Do not run `/doctor` automatically at the end — adopt-strands is structural, and the user can run doctor themselves once they've reviewed. Auto-running it would interrupt the natural follow-up of `/switch-strand`.
