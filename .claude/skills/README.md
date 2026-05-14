# COMPACT

**C**ontext · **M**emory · **P**rompt — **A**udited, **C**o-developed, **T**eam-locked.

A portable prompt/context/memory engineering framework for team-based AI-assisted software development. Works identically in Claude Code and Cline.

The name captures the core idea: memory-as-contract (a *compact* between human and AI) and tightly-packed team lockstep.

## What this is

A set of 13 skills plus templates that, together, give a team:

- **A shared ritual** — session-start to hydrate context, close-session to persist progress and decisions.
- **Phase discipline** — explicit Requirements / Architecture / Development lenses you switch between deliberately.
- **An auditable code map** — `MODULE.md` files co-located with code, plus a regenerated `MAP.md` so AI-generated code isn't a black box.
- **A decision log** — ADR-style `DECISIONS.md` where non-obvious choices are anchored; linked from `MODULE.md` for grounded "why" queries.
- **Drift detection across layers** — `drift-check` surfaces mismatches between requirements, design, and implementation. Interactive resolution; no auto-fix.
- **Parallel work via strands** — `start-strand` / `switch-strand` / `land-strand` create per-work-item folders that isolate journals and draft decisions so multiple devs can run sessions in parallel without colliding on STATUS.md or DECISIONS.md.

Designed to work identically across Claude Code (Anthropic) and Cline (any model, including team-internal LLMs). Both tools read `.claude/skills/` and share the `SKILL.md` format.

## Installation

Run the install script to copy the skill bundle into a project's `.claude/skills/` (same path for Claude Code and Cline):

```bash
/home/mohan/work/utils/skills/compact/install.sh /path/to/project
```

The script uses `rsync` under the hood and deliberately excludes the reference graphics (`COMPACT_Cheatsheet.*`, `COMPACT_Overview.*`) — those stay in this source tree as onboarding material and should not land inside a target project's `.claude/skills/`.

Add the auto-trigger one-liner. Tools read different files, so pick based on which tool(s) the team uses — both can coexist harmlessly in the same repo:

- **Claude Code users:** create `CLAUDE.md` at repo root.
- **Cline users:** create `.clinerules` at repo root.

```
At the start of any new conversation, invoke the `session-start` skill.
If the conversation has been auto-compacted since the last `session-start`,
re-invoke it before continuing work so Tier 1 state (PROJECT.md, STATUS.md,
active phase, relevant MODULE.md) is reloaded from disk.
```

**Cline also requires:** the VS Code Cline extension installed and its model provider configured (Base URL, API key, model ID). See `COMPACT_Overview.md` Part 8 for the full Cline setup — extension, provider config, `.clineignore`, and auto-approve settings (keep writes in `docs/compact/` **off** auto-approve — every memory-file edit should be human-reviewed).

Start a new Claude Code or Cline session. `session-start` will detect the uninitialized project and offer to run `/project-init`.

## Skills

| Skill | Purpose |
|---|---|
| `compact` | Orientation only. Prints the methodology overview and points to the sub-skills. Read-only. Invoke when onboarding or for a refresher. |
| `session-start` | Hydrate session: load PROJECT/MAP/STATUS + active phase file; surface state; ask intent; load task-specific `MODULE.md` on demand. |
| `switch-phase` | Switch between `requirements`, `architecture`, `development` lenses. Loads phase file; updates active phase in STATUS.md. |
| `close-session` | Recap work; two-pass decision triage; diff-based STATUS update; MODULE.md soft/hard-flag audit; conditional `regen-map`; propose commit. Never auto-writes. |
| `regen-map` | Regenerate `MODULE.md` Structure sections + rebuild `MAP.md` from code. Phase-aware orphan detection. Self-checking (reverts any curated-section edit). |
| `project-init` | Run the 7-topic interview, customize 3 phase prompts from base prompts, scaffold `docs/compact/`. `--re-init` regenerates phase prompts without touching state files. `--retrofit` adds a codebase-scan preflight for existing projects: detects languages, seeds MODULE.md skeletons, writes a polyglot-aware `structure-conventions.md`, and produces an initial `MAP.md`. |
| `drift-check` | Detect and resolve drift across the R/D/I layers: requirements (`requirements.md`) vs design (`MODULE.md` + architecture ADRs) vs implementation (code). Four modes (`requirements` / `design` / `dev-full` / `dev-module`) plus `all`. Interactive — user decides direction per drift. Never auto-fixes, never auto-cascades. Deferred items surfaced separately, not flagged. |
| `doctor` | Audit scaffold internal consistency: schema authorities (generative from README), stale refs, skill inventory, step monotonicity + step-reference resolution, tool-neutral framing, path canonicalization, cross-file references. Also audits project-runtime strand state when adopted. Read-only. Auto-invoked by `close-session` every session. |
| `start-strand` | Scaffold a new strand at `docs/compact/strands/<name>/` with `STRAND.md` + `journal.md` + `decisions-draft.md`. Interviews for summary / target modules / assignees. Does not bind the session — call `/switch-strand` after. |
| `switch-strand` | Bind the current session to a strand. Writes `.compact/current-strand` (gitignored, per-clone). `close-session` and `switch-phase` honor the binding. Pass `none` to unbind. |
| `list-strands` | Show active strands as a table — status, assignees, target modules, last activity. Highlights the currently-bound strand. `--include-archived` adds landed/abandoned strands. Read-only. |
| `land-strand` | Architect-driven terminal event: promotes each entry in `decisions-draft.md` to canonical `DECISIONS.md` with the next sequential `D-XXX`, marks `STRAND.md` landed, moves the folder to `strands/_archive/`. Single-writer — coordinate across clones. |
| `adopt-strands` | One-time retrofit for an existing COMPACT project. Scaffolds `strands/` + `_archive/`, seeds 0-N strands from `STATUS.md` in-flight items, stamps a cutover banner. |

## Artifacts produced by `project-init`

```
docs/compact/
  PROJECT.md                    # 1-page identity: who / why / scope boundaries (human-curated)
  requirements.md               # Behavioral specs: FR / NFR / Deferred (human-curated)
  STATUS.md                     # Active phase + Done / In progress / Next / Flags + drift-check marker
  DECISIONS.md                  # Append-only ADR log (immutable entries)
  MAP.md                        # Regen-generated module map + Mermaid
  structure-conventions.md      # Per-repo: what's a module, visibility mapping
  project-init-interview.md     # Persisted 7-topic answers (source for --re-init)
  phases/
    requirements.md             # Phase prompt (customized from base prompts) — NOT the same as docs/compact/requirements.md
    architecture.md             # Phase prompt (customized from base prompts)
    development.md              # Phase prompt (customized from base prompts)

src/<module>/MODULE.md          # Co-located module docs (doc-first at architecture)
```

**Note:** `docs/compact/requirements.md` (behavioral specs) and `docs/compact/phases/requirements.md` (the requirements-phase AI persona) are two different files. The specs are the *what*; the phase prompt is *how the AI behaves when working on requirements*. Keep them distinct when reading or referencing.

## The `MODULE.md` schema

Each module has a `MODULE.md` co-located with its code. Curated sections are hand-written (doc-first during architecture phase); the Structure section is regenerated from code by `regen-map`.

```markdown
# <module>

**Owner**: <name>          <!-- optional; add when a single contributor owns the module -->

**Purpose**
1-2 sentences.

**Public surface**
- `signature` — semantic, incl. non-obvious failure/return.
- `impl <Trait> for <Type>` — when callers rely on it.

**Invariants**
- Threading, state lifecycle, ordering guarantees.

**Key choices**
- <choice> — [D-XXX](../../docs/compact/DECISIONS.md#d-xxx)

**Non-goals**
- What this module deliberately does NOT do.

<!-- BEGIN:STRUCTURE -->
<!-- Regenerated by regen-map. Do not hand-edit. -->
<!-- END:STRUCTURE -->

**Depends on**: [mod-a](../mod-a/MODULE.md)
**Depended on by**: [mod-b](../mod-b/MODULE.md)

**Deferred** <!-- optional; planned-but-unbuilt behaviors for this module. Written by drift-check or hand-added. -->
```

## Strands — parallel work without collision

When multiple team members or multiple in-flight work items run on the same repo, the *journal* surface (STATUS.md + DECISIONS.md as it accumulates draft entries mid-flight) becomes a collision hotspot. Strands solve that by giving each chunk of work its own folder of in-flight state.

```
docs/compact/strands/
├── llm-upgrade/
│   ├── STRAND.md                    # title, status, assignees, target modules, summary
│   ├── journal.md                   # append-only per-session log
│   └── decisions-draft.md           # draft decisions awaiting promotion at land time
├── pipeline-refactor/
│   └── ...
└── _archive/
    └── <previously-landed strands>/
```

**Lifecycle.** `/start-strand <name>` once → many `/switch-strand <name>` + `/switch-phase` + `/close-session` (writes go to the strand's journal + drafts) → `/land-strand <name>` once when work ships (promotes drafts to canonical `DECISIONS.md` with sequential `D-XXX`, archives the folder).

**Per-clone binding.** `/switch-strand` writes `.compact/current-strand` (gitignored). Each clone has its own binding — two teammates can be in different strands at the same time on the same repo.

**What stays canonical.** `MODULE.md` curated sections, `MAP.md`, `DECISIONS.md` (promoted entries), and architect-owned `STATUS.md` updates. Strands intercept the *journal* surface only; the design layer is unchanged.

**Retrofit.** Existing COMPACT projects adopt strands with a single one-shot `/adopt-strands` run that scaffolds the directory, optionally seeds 0-N strands from current `STATUS.md` in-flight items, and stamps a cutover banner.

## Design principles

- **Markdown files hold substance; skills orchestrate.** Everything durable is plain markdown the team can read and edit.
- **Progressive loading.** Tier 1 (PROJECT + MAP + STATUS + active phase) always; `MODULE.md` on demand; `DECISIONS.md` entries only when referenced.
- **Propose, don't write.** Skills that change files always show diffs first.
- **Detect, don't auto-resolve.** Drift, orphans, and phase-boundary violations are surfaced — humans decide.
- **Deterministic regeneration.** `regen-map` output is byte-identical for byte-identical input. Diffs reflect real changes only.
- **Immutable decision log.** `DECISIONS.md` entries are never edited; they're superseded by new entries with forward/backward links.
- **Contributors drive design.** Stakeholder interfaces (web UIs, intake forms, correction queues) are first-class modules — not admin-tool afterthoughts.

## Contributors as design driver

AI-assisted projects fail when only devs can contribute. COMPACT pulls stakeholder involvement to Day 1: the `/project-init` interview captures **every** stakeholder (TPM, QA, domain expert, end user) with their contribution type, required interface, and feedback loop. That table goes into `PROJECT.md` and drives:

- **Architecture** — every non-trivial contribution surface becomes a first-class module with its own `MODULE.md`, designed doc-first.
- **Tech stack** — must support the interfaces stakeholders need (a CLI-only stack can't serve a TPM who needs a web UI; the mismatch surfaces during the interview).
- **Sessions** — `close-session` scans file-based contribution drop-paths each session and surfaces new stakeholder artifacts for review.

See the `Contributors` table in `PROJECT.md` (worked example in `project-init/templates/PROJECT.md`).

## Vendored base prompts

The `project-init/base-prompts/` directory contains snapshots of the prompt library at [github.com/kurnoolion/prompts-lib](https://github.com/kurnoolion/prompts-lib):

- `00-swdev-project-customizer.md` — the meta-prompt (7-topic interview + customization rules)
- `01-swdev-requirement-gathering.md` — requirements-phase base prompt
- `02-swdev-architecture-design.md` — architecture-phase base prompt
- `03-swdev-development-testing-debugging.md` — development-phase base prompt

Re-vendor periodically: `curl -o base-prompts/<file> https://raw.githubusercontent.com/kurnoolion/prompts-lib/main/<file>` or invoke `project-init --fetch-latest`.

## First-run flow

Slash-command syntax below is Claude Code. In Cline, invoke the same skills by natural request — e.g. `run the project-init skill`, `run the switch-phase skill with arg architecture`. See `COMPACT_Overview.md` Part 8 for the full Cline mapping.

1. User opens a new conversation in Claude Code or Cline.
2. `CLAUDE.md` / `.clinerules` one-liner triggers `session-start`.
3. `session-start` detects an empty `docs/compact/` and offers `/project-init`.
4. `/project-init` runs an optional preflight (import existing design docs into `docs/compact/design-inputs/`), the 7-topic interview, customizes phase prompts, and scaffolds state files.
5. `session-start` re-hydrates; user runs `/switch-phase requirements`.
6. User iterates on `PROJECT.md` (seeded from design inputs if provided); `/close-session` commits.
7. Next session: `/switch-phase architecture`; draft `MODULE.md` skeletons; `/close-session` captures decisions; `/regen-map` updates MAP.
8. Subsequent sessions: `/switch-phase development`; implement against the contracts in `MODULE.md`; `/close-session` audits.

**Bringing in existing design work:** if you drafted a design doc in Claude web, ChatGPT, or another tool before starting, `/project-init` asks for it upfront. Paste it or give a file path; it lands in `docs/compact/design-inputs/` and the generated requirements + architecture phase prompts automatically reference it as a starting proposal to refine. Greenfield projects just reply `skip`.

## Retrofitting an existing project

If the project already has requirements, design docs, and/or code, run `/project-init --retrofit` instead of vanilla init. The preflight adds a codebase scan on top of the design-inputs import:

- **Language detection** — scans for manifest files (`Cargo.toml`, `go.mod`, `pyproject.toml`, `package.json`, …) and surfaces the list for your confirmation. You can add any missed.
- **Module discovery** — applies per-language conventions (Rust `src/<mod>/`, Go `pkg/` / `cmd/` / `internal/`, Python `__init__.py` dirs, TypeScript `src/` or `packages/*/src/`) to collect candidate modules.
- **Public-surface extraction** — greps each candidate module for top-level public items. Results become commented-out *candidates* in the seeded `MODULE.md` — a reviewable list, not a curated contract.
- **Archival snapshot** — everything written to `docs/compact/retrofit-snapshot.md`, read once by the interview and by the customizer's phase-prompt generation; nothing after.

Retrofit then:

- Seeds `src/<module>/MODULE.md` skeletons at each detected path, each prefixed with `<!-- retrofit: skeleton -->`. While this sentinel is present, `close-session`'s hard-flag audit treats curated-section edits as expected. Remove the sentinel once the MODULE.md is fully curated.
- Writes a **polyglot-aware** `structure-conventions.md` — one section per confirmed language, each with its own Module definition and Visibility mapping. `regen-map` iterates per language.
- Sets active phase to `architecture` (not `requirements`). The team's next work is curating contracts, not discovering requirements.
- Offers opt-in **reconstructed decisions** — observed choices (runtime, storage, framework) can be anchored as `DECISIONS.md` entries with `status: reconstructed` and today's date. Rationale is explicitly *not* backfilled; only the choice is recorded, plus a `TODO` for Consequences.
- Runs `regen-map` once to produce an initial `MAP.md`.

Post-retrofit, the standard workflow applies: curate MODULE.md skeletons module-by-module, remove each sentinel when done, and `/close-session` at the end of every session.

## Drift detection across R/D/I layers

COMPACT keeps three layers in play — **requirements** (`docs/compact/requirements.md`, FR/NFR specs), **design** (`MODULE.md` curated sections + ADRs in `DECISIONS.md`), and **implementation** (code). As work progresses, these layers drift apart: a session introduces a behavior that's not in any FR; a MODULE.md invariant contradicts a newly-added NFR; a module's code silently outgrows its declared Public surface.

`/drift-check` detects and helps resolve that drift. Four modes plus a guided cascade:

| Mode | What it compares |
|---|---|
| `/drift-check requirements` | Session discussion / recent commits vs `requirements.md` |
| `/drift-check design` | `MODULE.md` curated sections + architecture ADRs vs `requirements.md` |
| `/drift-check dev-full` | All modules' code vs their `MODULE.md` |
| `/drift-check dev-module <name>` | One module's code vs its `MODULE.md` |
| `/drift-check all` | `requirements` → `design` → `dev-full`, with user approval at each descent |

Every drift is presented with the evidence from both layers (`file:line` on each side). The user picks the direction: update layer A, update layer B, specify both, skip, or mark the item as deferred. The skill never auto-decides, never auto-cascades, and writes nothing until the user approves the combined diff.

**Deferred is not drift.** Each artifact carries its own `## Deferred` section — `requirements.md` for deferred specs, `MODULE.md` for deferred design elements, inline `TODO(deferred: <reason>)` for deferred implementation bits. Drift-check reads all three and classifies matching items as `[DEFERRED]` with a one-line note, not as findings that need action.

**IDs are stable.** `FR-N` and `NFR-N` are never renumbered; removed requirements are struck through in place (`~~**FR-3** — ...~~`) so the history stays traceable. Retrofit projects preserve their pre-existing IDs verbatim (a `REQ-042` stays `REQ-042` — only new additions use the COMPACT default).

`/close-session` emits a non-blocking **drift-check nudge** when a session has touched multiple layers (requirements + design, design + code, or all three), or when drift-check hasn't run in a while. It's a one-line suggestion, not a gate — `skip` to commit without running.

## Long sessions and auto-compaction

Claude Code auto-summarizes earlier portions of a conversation when approaching the context limit. The summary preserves intent but can lose specific file contents. COMPACT is designed to make this largely harmless — the authoritative state (`PROJECT.md`, `STATUS.md`, `DECISIONS.md`, `MAP.md`, active phase file, `MODULE.md` files) lives on disk, not in conversation history. What compaction can lose, a re-read can restore.

Three habits make this a non-issue in practice:

1. **Re-invoke `session-start` after compaction or when context feels stale.** It's idempotent and cheap — reloads Tier 1 from disk in a single pass. Trust the files over model recall.
2. **Checkpoint often with `close-session`.** Once progress is captured into `STATUS.md` + `DECISIONS.md`, a later compaction can lose chat detail without losing the work.
3. **Ask the AI to re-read before acting on specifics.** "Re-read `src/<module>/MODULE.md` before you propose that change." Good habit on any long-running task.

Cline doesn't auto-compact, so habits 1-3 are team ritual rather than tool-enforced. Claude Code users can optionally automate a post-compaction reminder by adding a `PreCompact` hook to the project's `.claude/settings.json`:

```json
{
  "hooks": {
    "PreCompact": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "echo 'COMPACT: conversation being auto-compacted. After compaction completes, re-invoke /session-start to re-hydrate state from disk (PROJECT.md, STATUS.md, active phase file, relevant MODULE.md).'"
          }
        ]
      }
    ]
  }
}
```

The hook's stdout becomes part of post-compaction context, so the reminder survives the summarization step. Verify the exact schema against current Claude Code hook docs — the `PreCompact` event and the `hooks[].hooks[].command` structure are the pieces you're targeting.

## Overview deck

`COMPACT_Overview.md` in this directory is a Marp presentation that walks a team through the methodology, workflow, and dual-tool (Claude Code + Cline) setup. Render with `marp COMPACT_Overview.md -o COMPACT_Overview.pptx`, or open in VS Code with the Marp extension for live preview.

## Status

This scaffold is the implementation of a design spec that is still evolving. Expect edits as real-world use surfaces gaps.
