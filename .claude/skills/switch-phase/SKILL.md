---
name: switch-phase
description: Switch the active project phase. Takes a phase name (requirements, architecture, development) and an optional comma-separated module list for architecture/development. Loads the phase lens from docs/compact/phases/<phase>.md, optionally loads MODULE.md for the listed modules plus one hop of their declared dependencies, and updates Active phase in STATUS.md. Thin orchestrator; phase substance lives in data files.
---

## Arguments

1. **Phase name** (required): one of `requirements`, `architecture`, `development`.
2. **Modules** (optional, architecture/development only): comma-separated list of module names to pre-load into context, e.g. `graph,parser`. Ignored for `requirements` — requirements work is code-agnostic.

## Procedure

Every step below is **idempotent**: check whether the effect is already present before performing it. See the "Already-loaded check" rule below for the heuristic.

1. **Validate** the phase argument. If not one of `requirements` / `architecture` / `development`, abort:

   > "Unknown phase: `<phase>`. Valid phases: requirements / architecture / development."

2. **Load the phase file.** If `docs/compact/phases/<phase>.md` has already been read this session and has not been modified since, skip the read and re-affirm the persona from existing context. Otherwise read it in full. Adopt the persona described there for the remainder of the session.

3. **Load module context** (architecture/development only).

   **Determine the effective module list.**
   - If the user supplied `<modules>`, use that list.
   - Otherwise, if a strand is bound (read `.compact/current-strand`; if file exists and points at a valid active strand), read its `STRAND.md` and use the `Target modules:` field as the list — provided that field is non-empty and not `unspecified`. Surface this to the user: "Using bound strand `<name>`'s target modules: <list>."
   - Otherwise (no arg, no usable strand list), do not auto-load anything. After step 5, suggest: "No modules specified and no usable strand target list. Read `docs/compact/MAP.md` for the module list, then re-invoke as `/switch-phase <phase> <m1,m2>` to focus context."

   **Load the determined list.**
   - For each name `M` in the effective list, locate its MODULE.md via the canonical path in `docs/compact/structure-conventions.md` (e.g. `src/<M>/MODULE.md`). If a named module isn't found, warn and continue with the rest.
   - Build the full target set: each named module's MODULE.md plus one hop of its declared **Depends on** edges (parse from the loaded MODULE.md). De-duplicate.
   - For each MODULE.md in the target set, apply the already-loaded check. Read only those that are missing or stale.
   - Never recurse past one hop — deeper transitive loading defeats the point of explicit scoping.

   **Offer to enrich the strand target list.** If the user supplied `<modules>` *and* a strand is bound *and* the supplied list contains modules not in the strand's `Target modules:` field, ask once after step 5: "Add `<delta>` to strand `<name>`'s target modules? (yes / no)" — on yes, edit `STRAND.md` to extend the field.

4. **Update STATUS.md and (if bound) STRAND.md.**
   - **STATUS.md:** if the current file already has `Active phase: <phase>` and `Last updated:` equal to today's date, skip the write. Otherwise set both lines. No other edits.
   - **STRAND.md (if bound):** if the strand's `Active phase:` field already equals `<phase>`, skip. Otherwise update it to `<phase>`. No other edits.

5. **Confirm.** Tell the user:

   > "Active phase: <phase>. Persona: <one-line summary from the phase file>."
   >
   > When modules were loaded, append: "Loaded modules: <explicit list> (+ one-hop deps: <dep list>)."
   >
   > When a step was skipped as already-current, note it compactly — e.g. "Phase already active; no change." or "Modules already in context: <list>; loaded only: <delta>."
   >
   > If every step was a no-op (same phase, all targets already loaded, STATUS current), the full message is: "Already in `<phase>` with requested modules loaded. No change."

## Rules

- Do not change code as a side-effect of switching.
- Do not modify any file other than STATUS.md's Active phase / Last updated lines, and (if a strand is bound) STRAND.md's Active phase / Target modules fields.
- Module loading is read-only and one-hop-deep. Never recurse beyond the first dependency level; the point of the explicit list is to keep context scoped.
- A stale strand binding (file present but pointing at a missing or archived strand) is treated as "no strand bound" for module-defaulting purposes. Surface the staleness once; do not abort — that's `doctor`'s and `switch-strand`'s job to clean up.
- **Already-loaded check.** A file is treated as "already in context" if it was Read earlier in this session *and* no Edit / Write / regen-map run has touched it since. If either condition fails, re-read. When in doubt, re-read — stale context is worse than a duplicate read.
- If the user's described intent seems to mismatch the phase they requested (e.g., they describe architecture work but asked for development), flag the mismatch but do not override.
- If `docs/compact/phases/<phase>.md` is missing, abort:

  > "Phase file `docs/compact/phases/<phase>.md` not found. For a new project, run `/project-init`. For an initialized project where the file was deleted or never generated, regenerate phase prompts with `/project-init --re-init` (state files are preserved)."
