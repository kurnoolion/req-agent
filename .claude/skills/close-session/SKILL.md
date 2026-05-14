---
name: close-session
description: Close a work session. Recaps work (user-authoritative), captures decisions via two-pass triage, updates STATUS.md via diff, audits MODULE.md curated-section edits with soft/hard flag classification, triggers regen-map if structure changed, and proposes a commit. Never auto-writes; never auto-commits.
---

Propose-don't-write throughout: every change is a diff the user approves.

## Strand binding (preflight)

Before step 1, read `.compact/current-strand` if it exists. If it contains a non-empty line:

- Resolve the named strand at `docs/compact/strands/<name>/`. If the directory doesn't exist (binding points at nothing or at an archived strand), warn the user, clear the stale binding, and proceed with `STRAND_BOUND = false`.
- Otherwise set `STRAND_BOUND = true` and capture `STRAND_NAME = <name>`.

When `STRAND_BOUND` is **true**:
- Step 2's session journal goes to `docs/compact/strands/<STRAND_NAME>/journal.md` (not STATUS.md).
- Step 3's drafted decisions go to `docs/compact/strands/<STRAND_NAME>/decisions-draft.md` (not canonical DECISIONS.md).
- The architect-only canonical files (`STATUS.md` global state, `DECISIONS.md` promotions) are not touched. They change only via direct architect edits or via `/land-strand`.

When `STRAND_BOUND` is **false**: every step below operates on canonical files as before — the strand layer is invisible.

Surface the binding to the user at the start:

> "Strand bound: `<STRAND_NAME>` — journal + draft decisions will route there." (or)
> "No strand bound — writes go to canonical STATUS.md / DECISIONS.md."

## Procedure

### 1. Recap

Summarize the session: files touched, tasks completed, problems encountered. Show to user.

Ask:

> "Does this match your memory? Anything missing?"

Long sessions have lossy recall — **treat the user's memory as authoritative.** Incorporate any additions before proceeding.

### 2. Propose journal / STATUS update

**If `STRAND_BOUND`:** draft an append-only journal entry for `docs/compact/strands/<STRAND_NAME>/journal.md`. Use this template:

```markdown
## <today's YYYY-MM-DD> — <short session title (auto-gen, user can edit)>

### Done this session
- <bullet items>

### In progress
- <bullet items>

### Next
- <bullet items>

### Flags
- <only when something is unresolved or noteworthy>
```

Existing journal content above this entry is untouched — strand journals are append-only, never rewritten. Show the diff (which is purely additive). Wait for approval before writing.

**If not `STRAND_BOUND`:** load current `docs/compact/STATUS.md` and draft diffs:

- Completed items: move **In progress → Done** (add today's date).
- Add new **In progress** items started mid-session.
- Update **Next** based on what logically follows.
- Preserve existing structure. **Do not rewrite wholesale.**

Show the diff. Wait for approval before writing.

### 3. Capture decisions — two-pass triage

**Pass 1 (triage).** Scan the session for candidates that match the DECISIONS filter:

- Reversing would take >1 day of rework.
- A reviewer would reasonably ask "why not X?"
- Multiple options were actually considered.
- Affects module boundaries, public APIs, or persistent data shapes.
- Deliberate perf / correctness / security tradeoff.

Present candidates as a numbered list with one-line summaries. Ask the user to mark each: `log` / `skip` / `unsure`.

**Pass 2 (capture).** For each `log` and `unsure` item, walk the decision template by asking plain-language questions:

- "What problem prompted this?" → **Context**
- "What did we choose?" → **Decision**
- "Why this over the alternatives?" → **Why**
- "What does this force on us?" → **Consequences**

**Never fabricate rationale.** If the user can't answer a field, mark it `TODO` and add the item to the session's Flags (strand journal or STATUS.md, per binding).

**Where the drafted entry lands depends on `STRAND_BOUND`:**

- **If `STRAND_BOUND`:** assign a draft ID — the next `D-DRAFT-N` within `docs/compact/strands/<STRAND_NAME>/decisions-draft.md`. Show the drafted entry. On approval, append. Do **not** touch canonical `DECISIONS.md` — promotion happens at `/land-strand` time, when the architect assigns a real `D-XXX` and the entry is approved one more time.
- **If not `STRAND_BOUND`:** assign the next sequential canonical `D-XXX` (read `docs/compact/DECISIONS.md` for the highest existing ID, increment). Show the drafted entry. On approval, append to `docs/compact/DECISIONS.md`.

The draft and canonical templates are identical apart from the ID. A draft promoted at landing time keeps its body, gets a real ID, and a `Promoted from strand: <name>` provenance footer.

### 4. Audit MODULE.md edits

For each `src/<module>/MODULE.md` touched this session:

**Retrofit skeleton grace.** If the file begins with `<!-- retrofit: skeleton -->`, it's a `project-init --retrofit`-seeded skeleton in the process of being curated. Curated-section edits are expected, not flag-worthy. Surface a one-line note ("curating retrofit skeleton: <module>") and skip the hard/soft classification. If the session's edits fully populate the curated sections (no TODO placeholders remain), prompt: "This MODULE.md looks curated. Remove the `<!-- retrofit: skeleton -->` sentinel so future audits apply normal rules?"

For all other MODULE.md files, diff curated sections (Owner, Purpose, Public surface, Invariants, Key choices, Non-goals, Depends on / Depended on by, Deferred) against the last committed version.

Classify any changes:

- **Hard flag** — signature change; invariant change; Non-goal *removed*; dependency added/removed; Deferred item *removed* (without evidence it was implemented). Require one of: capture as decision, revert, or explicit note added to STATUS.md Flags.
- **Soft flag** — purely additive: trait/interface impl added; Public surface item added with new signature; Invariant *added* (not changed); Non-goal *added*; Deferred item *added*. Offer: capture as decision / accept as idiomatic (keep MODULE.md edit, no DECISIONS entry) / revert.

### 5. Detect structural changes

If any of: new module added, module renamed, module deleted, or dependency edges changed → **invoke `regen-map`**.

Otherwise skip regen and tell the user which case applied.

Surface `regen-map`'s full output, including any self-check reverts.

### 6. Scan contribution drop-paths

Read `docs/compact/PROJECT.md` Contributors table. For every row whose **Feedback loop** column names a file-based drop-path (e.g. `contributions/eval/*.yaml`, `contributions/corrections/`), check that path for new or modified artifacts since the last commit.

For each finding:

- List the files and the stakeholder role they came from.
- Ask the user: route to pipeline (ingest now), defer (log in Flags), or reject (note why)?
- **Do not auto-ingest.** Stakeholder contributions are inputs that affect AI behavior — they deserve the same review as decisions.

Skip this step entirely if the Contributors table has no file-based loops (all contributions come through git, web UI, or issue tracker).

### 7. Drift-check nudge (soft, non-blocking)

Read the `Last drift-check:` marker from STATUS.md (if present) and compute the session's touched layers:

- Edited `docs/compact/requirements.md` → requirements layer touched.
- Edited curated sections of any `MODULE.md`, or appended an entry to DECISIONS.md during architecture phase → design layer touched.
- Edited code under `src/` → implementation layer touched.

Nudge **if either** trigger fires:

- Multiple layers were touched this session, **or**
- The last drift-check is more than ~10 sessions old (or never).

Suggest a mode based on which layers were touched:

- Requirements + design → `/drift-check design`.
- Design + implementation → `/drift-check dev-full` (or `dev-module <name>` if only one module was touched).
- All three → `/drift-check all`.
- Requirements only → `/drift-check requirements`.
- Design only → `/drift-check design`.
- Implementation only → `/drift-check dev-full` (or `dev-module <name>` if only one module was touched).
- No layer touched (stale-only trigger) → `/drift-check all`.

Surface as a one-line nudge:

> "Drift-check nudge: <reason>. Consider `/drift-check <mode>` before committing. (Non-blocking — `skip` to continue.)"

**Do not auto-invoke drift-check.** If the user chooses to run it, pause close-session; on return, re-enter at step 8. If they skip, continue. If the suggestion is declined repeatedly across sessions, do not escalate — the nudge stays soft.

### 8. Produce summary

- Files changed in `docs/compact/` and `src/**/MODULE.md`.
- Unresolved items → write to STATUS.md **Flags** section for next session.
- Draft commit message: short imperative; reference any new `D-XXX` IDs.

### 9. Scaffold consistency audit

Invoke the `doctor` skill unconditionally. Runs every close-session regardless of whether scaffold files changed this session — stale cross-references and generative-quorum gaps can accumulate even in sessions that don't touch the scaffold, and `doctor` is cheap and read-only.

- Surface its full output verbatim.
- On failures: user must address (fix now) or defer (note in STATUS.md Flags) before commit. `doctor` never auto-fixes.

### 10. Commit decision

Show the full diff once more. Ask: `commit` / `stage only` / `abort`.

- `commit` → commit with the drafted message.
- `stage only` → `git add` the changes; leave commit to the user.
- `abort` → do nothing further. Prior approved writes (STATUS, DECISIONS appends, MODULE.md audit outcomes, contribution-path routing, drift-check edits if the nudge was accepted) are **not** reverted — they were approved individually.

**Never auto-commit. Never skip diff review.**

## Rules

- Docs-only skill. Never modify code.
- Never auto-log decisions without user confirmation.
- Never invent decision rationale — ask the user or mark `TODO`.
- Never rewrite STATUS.md or strand journals wholesale — STATUS is updated in place, journals are append-only.
- Never silently accept curated-section changes in MODULE.md.
- When a strand is bound, never write to canonical STATUS.md / DECISIONS.md — those are reserved for architect-only edits and `/land-strand` promotions.
- A stale strand binding (pointing at a missing or archived strand) is recovered transparently: warn, clear `.compact/current-strand`, and continue in unbound mode. Do not abort the session over a binding hygiene issue.
- Output should be PR-quality: a reviewer should be able to skim it.
