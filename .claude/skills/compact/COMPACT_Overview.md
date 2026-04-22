---
marp: true
theme: default
paginate: true
header: 'COMPACT — Overview'
footer: 'Internal use'
style: |
  section { font-size: 22px; }
  h1 { font-size: 40px; }
  h2 { font-size: 32px; }
  code { font-size: 18px; }
  table { font-size: 18px; }
---

<!-- _class: lead -->
<!-- _paginate: false -->

# COMPACT

### A shared workflow for prompt, context, and memory engineering

**C**ontext · **M**emory · **P**rompt — **A**udited, **C**o-developed, **T**eam-locked.

One system, two tools: Claude Code (personal) + Cline (work, internal LLM).
Same skills. Same markdown. Same rituals.

---

## Why "COMPACT"?

The name is load-bearing. Two meanings we wanted:

1. **A compact** — a binding agreement. In our workflow, the markdown files in `docs/compact/` *are* the contract between human, AI, and team. Nothing important lives in chat history; everything durable is a diff-reviewed file.
2. **Compact** as in *tightly-packed, in lockstep*. The whole point is keeping a team moving together when multiple people are partnered with AI on the same codebase.

The letters map to the three engineering disciplines (**C**ontext, **M**emory, **P**rompt) plus the three team values (**A**udited, **C**o-developed, **T**eam-locked).

---

## What we'll cover

1. **The problem** — why ad-hoc AI coding breaks down in teams
2. **Three engineering disciplines** — prompt, context, memory
3. **Why we built this** — design rationale
4. **How it keeps us in lockstep** — the shared contracts
5. **The system** — skills, files, schemas
6. **The workflow** — session start to session close
7. **A dry run** — walking a small feature end-to-end
8. **Using this in both tools** — Claude Code and Cline setup + usage
9. **Getting started** — setup, checklist, FAQ

Expected time: ~90 minutes with discussion.

---

## What you'll leave with

- A mental model for how we want to work with Claude going forward.
- A concrete ritual for starting and closing every session.
- Confidence that Claude-generated code is **not** a black box — you can audit it.
- Shared vocabulary (phases, decisions, invariants) so review conversations are crisp.

---

# Part 1 — The problem

---

## Today's reality with AI-assisted dev

- Each developer has a slightly different way of prompting Claude.
- Context gets lost between sessions. You rediscover the same things.
- Claude writes code that *works* but nobody on the team can explain *why* a specific design was chosen.
- Reviewing an AI-generated PR feels harder than writing it yourself.

None of this is fatal on day one. By month three, the codebase feels like a stranger.

---

## What specifically goes wrong

| Problem | Root cause |
|---|---|
| Hallucinated APIs or wrong assumptions | Weak grounding at the moment of generation |
| Conflicting design choices in the same repo | No captured decisions to reference |
| "Why did we do it this way?" has no answer | Rationale never recorded |
| Every new session re-explores scope | No persistent shared context |
| Team members work out of sync | No common artifacts to anchor discussion |

---

## Why these don't just go away with better prompts

A *good* prompt asks Claude to do one thing well.

But a **team** working on a **living codebase** over **months** needs more than one-off prompts. It needs:

- Persistent shared state.
- A protocol for capturing decisions.
- A protocol for auditing what was produced.
- A protocol that survives tool changes (Claude Code, Cline, internal LLMs).

That's what we're building here.

---

# Part 2 — Three engineering disciplines

---

## The three layers

```
┌─────────────────────────────────────────────────┐
│  PROMPT ENGINEERING                             │
│  What we ask Claude to do, by phase.            │
├─────────────────────────────────────────────────┤
│  CONTEXT ENGINEERING                            │
│  What Claude sees when it works on a task.      │
├─────────────────────────────────────────────────┤
│  MEMORY ENGINEERING                             │
│  What persists between sessions, as markdown.   │
└─────────────────────────────────────────────────┘
```

Each layer has different concerns, different failure modes, and different remedies.

---

## Prompt engineering — defined

> The practice of shaping *what we're asking* — instructions, role, output format, constraints — so Claude produces what we actually want.

In isolation, prompt engineering is about one task.

In a team codebase, it's about **role-appropriate prompts at each phase of work**: requirements is a different persona than architecture, which is a different persona than development.

---

## Prompt engineering in our system

Three phase prompts live in `docs/compact/phases/`:

| Phase | Persona |
|---|---|
| **Requirements** | Help user articulate *what* and *why*. Ask, don't design. |
| **Architecture** | Decide *how* at module level. Draft MODULE.md doc-first. No code. |
| **Development** | Implement against contracts. Honor invariants. Capture decisions as they emerge. |

These are generated at project creation by a **meta-prompt** that fuses your domain answers with base templates from `prompts-lib`.

---

## How phase prompts get produced

```
project-init runs:
  ┌─────────────────────┐
  │ 7-topic interview   │  ← you answer once per project
  └──────────┬──────────┘
             │
             ▼
  ┌─────────────────────┐     ┌──────────────────┐
  │ Base prompts        │ ──▶ │ Customizer rules │
  │ (01, 02, 03)        │     │ (from meta-prompt)│
  └─────────────────────┘     └────────┬─────────┘
                                       │
                                       ▼
                  docs/compact/phases/requirements.md
                  docs/compact/phases/architecture.md
                  docs/compact/phases/development.md
```

The customizer injects your domain, stack, team structure, constraints, and pain points. You don't write prompts — you answer questions.

---

## Context engineering — defined

> The practice of making sure Claude has the *right* information in its context window at the moment it generates — not too little, not too much.

Counterintuitive fact: **more context usually makes responses worse**, not better. Attention dilutes. Quality degrades past ~30–50K loaded tokens.

Goal: **minimum viable context + reliable on-demand retrieval.**

---

## Context engineering in our system

Every session uses **progressive loading**:

| Tier | When loaded | Files |
|---|---|---|
| **1** | Always, at session start | `PROJECT.md`, `MAP.md`, `STATUS.md`, active phase file |
| **2** | On demand, once you state a task | `MODULE.md` files for modules in scope |
| **3** | On reference, when cited | Specific `DECISIONS.md` entries |

Tier 1 target: **≤5K tokens**. Tier 2 only loads what's relevant.

This is `session-start`'s job.

---

## Memory engineering — defined

> The practice of deciding *what to remember between sessions*, *where to put it*, and *how to keep it current* — so future sessions (and future team members) have durable context.

Claude itself has no memory between conversations. The session window is all it sees. If we don't explicitly persist things, they're gone.

---

## Why we make memory explicit — as markdown

We could let Claude handle memory internally. We chose not to. Three reasons:

1. **Memory becomes a contract.** When memory is a markdown file in the repo, you and your teammates can read, review, diff, and edit it. It's not hidden state.
2. **Portable across tools.** Claude Code, Cline, and your future tools can all read markdown. No vendor lock-in.
3. **Auditable.** PR reviews surface memory changes alongside code changes. Nothing slips in unseen.

---

## The memory files (every project)

```
docs/compact/
├── PROJECT.md              # Identity: who / why / scope (1 page, stable)
├── requirements.md         # Behavioral specs: FR / NFR / Deferred
├── STATUS.md               # Current state: Done/In-progress/Next/Flags + drift-check marker
├── DECISIONS.md            # Append-only ADR log (D-001, D-002, …)
├── MAP.md                  # Module layout + dependency diagram (regen)
├── structure-conventions.md # What's a module in THIS repo
├── project-init-interview.md # Your answers to the 7-topic interview
└── phases/
    ├── requirements.md     # Phase prompts (customized per project) — the AI's persona
    ├── architecture.md
    └── development.md

src/<module>/MODULE.md      # Co-located module docs
```

`docs/compact/requirements.md` (behavioral specs) is distinct from `docs/compact/phases/requirements.md` (the requirements-phase AI persona). Specs are *what*; the phase prompt is *how the AI behaves when working on them*.

Every file has a purpose. Every file is plain markdown.

---

# Part 3 — Why we designed this

---

## Team-first, not AI-expert-first

Most AI workflows assume the developer is fluent in prompt/context/memory engineering.

**Our team isn't, and shouldn't need to be.**

The system does the engineering work so you can focus on **software**. You answer questions during `project-init`. You work through phases. You review diffs at session close. That's the full user interface.

---

## Portable across Claude Code and Cline — by design

We use two tools **as equals**, not primary/fallback:

- **Claude Code** on personal machines — Anthropic's hosted Claude.
- **Cline** on work machines — our internal 200B+ reasoning LLM, no data leaving the network.

Both tools read `.claude/skills/` and share the SKILL.md format. One scaffold serves both.

**Implication:** every skill, schema, and ritual in this deck works identically in both tools. Markdown files are the lingua franca; skills are the orchestration layer that runs in either. We'll cover Cline-specific setup in Part 8.

---

## Audit, not black box

The biggest risk with AI-generated code is that we ship what we can't review. Our design fights this explicitly:

- `MODULE.md` documents **purpose**, **public surface**, **invariants**, **key choices**, **non-goals** — per module, co-located with code.
- `DECISIONS.md` anchors **why** choices were made — linked by ID from MODULE.md.
- `MAP.md` shows the **whole system layout** — regenerated from code, so it never rots.

"Why did Claude choose RwLock here?" → one click from MODULE.md to DECISIONS.md.

---

## Principles we settled on

1. **Markdown holds substance; skills orchestrate.** Everything durable is plain markdown.
2. **Progressive loading.** Tier 1 always, more on demand.
3. **Propose, don't write.** Skills that change files show diffs first.
4. **Detect, don't auto-resolve.** Drift and violations are surfaced; humans decide.
5. **Deterministic regeneration.** Same input → byte-identical output.
6. **Immutable decision log.** Decisions are superseded, never edited.
7. **Phases as lenses, not states.** Switch freely; low friction.
8. **Contributors drive design, not the other way around.** Stakeholder interfaces are first-class modules — not admin-tool afterthoughts.

---

## Principle 8 — Contributors as design driver

AI-assisted development isn't just devs + the LLM. Real projects have TPMs writing requirements, QA supplying eval sets, domain experts correcting AI output, end users giving UI feedback. If we only design for devs, the rest have no contribution path — and the system degrades.

COMPACT pulls this forward to Day 1:

- **Topic 3 of `/project-init`** asks for every stakeholder, what they contribute, what interface they need, and how their contribution reaches the pipeline.
- **`PROJECT.md` Contributors table** captures all of the above — *before* any code is written.
- **Architecture phase** treats each contribution surface (web UI, intake form, correction queue) as a first-class module with its own `MODULE.md`, designed doc-first.
- **Tech stack (topic 2)** is constrained by what topic 3 demands — a CLI-only stack can't serve a TPM who needs a web UI. Mismatches surface during the interview.
- **`close-session`** scans file-based contribution drop-paths each session and surfaces new stakeholder-provided artifacts for review.

The failure mode this prevents: a pilot that technically works but has no way for non-dev stakeholders to correct, validate, or extend — so it never graduates past the dev team.

---

## Example Contributors table

| Stakeholder / Role | Contributes | Interface | Feedback loop |
|---|---|---|---|
| Dev team | Code, design, reviews | Direct git | Normal PR flow |
| QA team | Eval sets, failure cases | `contributions/eval/*.yaml` drop | Ingested by CI on merge |
| TPM | Requirements clarifications | Web UI at `/admin/requirements` | Staged edits → dev review → `PROJECT.md` |
| Domain expert | Corrections on AI output | Structured form w/ diff view | Writes to `contributions/corrections/`, reviewed at close-session |
| End user | UI feedback, bug reports | In-app widget | Issue tracker → weekly triage |

Missing rows (unowned validation, no correction path, no eval channel) are v1 risks — surfaced in Open questions.

---

# Part 4 — How this keeps us in lockstep

---

## Shared vocabulary

Three words the whole team uses the same way:

- **Requirements** — we're figuring out *what* to build.
- **Architecture** — we're deciding *how* at the module level.
- **Development** — we're implementing against the contracts we set.

When someone says "let's switch to architecture," everyone knows what that means. No ambiguity.

---

## Shared artifacts

Everyone reads and writes the same files.

| File | Who updates it | When |
|---|---|---|
| `PROJECT.md` | Human, in Requirements phase | On scope change |
| `requirements.md` | Human, in Requirements phase; `drift-check` on approved resolutions | On behavior spec change |
| `STATUS.md` | `close-session` skill; `drift-check` updates the drift-check marker | Every session close |
| `DECISIONS.md` | `close-session` via Q&A; `drift-check` appends new ADRs when resolving drift | When decisions made |
| `MODULE.md` curated sections | Human, in Architecture phase; `drift-check` on approved resolutions | When contracts change |
| `MODULE.md` Structure section | `regen-map` skill | When code changes |
| `MAP.md` | `regen-map` skill | When modules change |

---

## Shared rituals

Every session follows the same shape:

```
┌─────────────────┐
│  session-start  │  Load context, ask intent
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  switch-phase   │  Adopt the right persona
└────────┬────────┘
         │
         ▼
   ┌──────────┐
   │   Work   │
   └─────┬────┘
         │
         ▼
┌─────────────────┐
│  close-session  │  Capture decisions, update status
└─────────────────┘
```

---

## Review surface

Every session close produces a **diff in `docs/compact/`** that a teammate can skim.

- What was worked on? → `STATUS.md`
- What decisions got made? → `DECISIONS.md`
- Did any module contracts change? → `MODULE.md` diffs
- Did the system shape change? → `MAP.md`

PR review isn't just about code anymore. It's about code + the memory artifacts that explain it.

---

# Part 5 — The system

---

## Directory layout (per project)

```
.claude/skills/            ← copied from the shared scaffold
  compact/SKILL.md
  session-start/SKILL.md
  switch-phase/SKILL.md
  close-session/SKILL.md
  regen-map/SKILL.md
  drift-check/SKILL.md
  doctor/SKILL.md
  project-init/
    SKILL.md
    base-prompts/
    templates/

docs/compact/                   ← created by project-init
  PROJECT.md  requirements.md  STATUS.md  DECISIONS.md  MAP.md
  structure-conventions.md  project-init-interview.md
  phases/{requirements,architecture,development}.md

src/<module>/MODULE.md     ← co-located with code
CLAUDE.md                  ← one-liner to auto-trigger session-start
```

---

## Skills at a glance

| Skill | What it does | When to invoke |
|---|---|---|
| `compact` | Orientation only — prints this methodology overview and points to the sub-skills | When onboarding or for a refresher |
| `project-init` | 7-topic interview; produces phase prompts + scaffolding. `--retrofit` for existing codebases (seeds MODULE.md skeletons + initial MAP.md) | Once, at project creation |
| `session-start` | Hydrate context; ask what you're working on | Start of every conversation |
| `switch-phase` | Adopt requirements/architecture/development persona | When switching phases |
| `close-session` | Persist work: decisions, status, audit; soft drift-check nudge when layers were touched | End of every session |
| `regen-map` | Refresh MODULE.md Structure and MAP.md from code | Invoked by close-session (or manually) |
| `drift-check` | Detect + resolve drift across R/D/I layers (requirements vs design vs implementation). Interactive; never auto-fixes | When close-session nudges, or on demand |
| `doctor` | Audit the scaffold itself for drift (stale refs, schema quorum, skill inventory, tool-neutral framing, step-reference resolution) | Auto-invoked by close-session every session (or manually) |

---

## session-start

**Goal:** hydrate session context in ≤5K tokens, then ask what you want to do.

1. Detects project state; offers `/project-init` if uninitialized.
2. Loads Tier 1: `PROJECT.md`, `MAP.md`, `STATUS.md`, active phase file.
3. Surfaces current state: phase, in-progress, next, flags.
4. Flags staleness: items >7 days old, unset phase, uncommitted docs.
5. Asks: "What are you working on this session?"
6. Loads Tier 2 (`MODULE.md`) based on your answer.

**Rule:** read-only. Never modifies files.

---

## switch-phase

**Goal:** adopt the right persona for the work you're about to do.

- Argument: `requirements | architecture | development`
- Reads `docs/compact/phases/<phase>.md`
- Updates `STATUS.md` active phase line
- Announces: "Active phase: X. Persona: Y."

**Rule:** thin orchestrator. All substance lives in the phase files, so they're editable without touching the skill.

---

## close-session

**Goal:** persist the session's work safely, with the user approving every write.

1. **Recap** — Claude summarizes, you correct. Your memory is authoritative.
2. **STATUS update** — diff-based. Move Done/In-progress/Next. No wholesale rewrite.
3. **Decisions** — two-pass: triage (log/skip/unsure), then fill template via plain-language Q&A.
4. **MODULE.md audit** — soft-flag vs hard-flag classification of curated-section edits.
5. **Regen-map** — conditional; only if modules changed.
6. **Commit proposal** — draft message; you choose commit / stage / abort.

**Rule:** never auto-writes, never auto-commits. Propose, don't write.

---

## regen-map

**Goal:** keep the derived docs (`MAP.md` + Structure sections) in sync with code. Never touches curated content.

- **Read-code-write-doc only.** Scans code; writes only between `<!-- BEGIN:STRUCTURE -->` / `<!-- END:STRUCTURE -->` markers.
- **Phase-aware**: MODULE.md without code is `[DRAFT]` during architecture, `[ORPHANED]` otherwise.
- **Detects drift**: declared Public surface vs actual code. Flags, doesn't auto-fix.
- **Never creates or deletes MODULE.md**. Those are architectural acts.
- **Self-checks**: reverts any file where a non-Structure byte changed.

**Rule:** alphabetical determinism — same input gives byte-identical output.

---

## project-init

**Goal:** turn a fresh repo into a working project in one guided interview.

1. Optional preflight: import existing design docs into `docs/compact/design-inputs/`.
2. Runs the 7-topic interview (from vendored meta-prompt).
3. Persists answers to `docs/compact/project-init-interview.md`.
4. Customizes the 3 phase prompts (fuses your answers with base templates).
5. Scaffolds `PROJECT.md`, `STATUS.md`, `DECISIONS.md`, `MAP.md`, `structure-conventions.md`.
6. Tells you: "Next step: `/switch-phase requirements`".

**Re-init:** `--re-init` regenerates phase prompts only. Never overwrites state files.

**Retrofit:** `--retrofit` for projects that already have code. See the next slide.

---

## project-init --retrofit

**Goal:** bring COMPACT to a project that already has requirements, design, and/or code.

**Extra preflight:**
- Detects languages from manifest files (Cargo.toml, go.mod, pyproject.toml, package.json). You confirm or add any missed.
- Discovers candidate modules per-language (Rust `src/<mod>/`, Go `pkg/` · `cmd/` · `internal/`, Python `__init__.py` dirs, TypeScript `src/` or `packages/*/src/`).
- Extracts public-surface candidates (top-level `pub` / `export` / capitalized / non-underscore) per module.
- Writes `docs/compact/retrofit-snapshot.md` — archival; read once, then never updated.

**Extra scaffolding:**
- Seeds `src/<module>/MODULE.md` at each detected path with a `<!-- retrofit: skeleton -->` sentinel + TODO placeholders + commented candidate-signature list under Public surface.
- Writes a **polyglot-aware** `structure-conventions.md` — one section per confirmed language. `regen-map` iterates per language.
- Sets `STATUS.md` active phase to `architecture` (not `requirements`). The gap is the contract, not the spec.
- Optionally anchors observed choices (runtime, storage, framework) as `DECISIONS.md` entries with `status: reconstructed`. User opts in per item; rationale is never invented.
- Runs `regen-map` once to produce the initial `MAP.md`.

**Post-retrofit:** curate MODULE.md skeletons module-by-module; remove the sentinel from each when curated; `/close-session` at the end of every session. `close-session`'s hard-flag audit gives sentinel-marked files a grace — normal audit applies the moment the sentinel is removed.

---

## drift-check

**Goal:** keep requirements, design, and implementation aligned — surface mismatches, let the user pick which layer changes.

Three layers, three distinct artifacts:

| Layer | Artifact |
|---|---|
| **R**equirements | `docs/compact/requirements.md` — FR-N / NFR-N / Deferred |
| **D**esign | `MODULE.md` curated sections + DECISIONS entries |
| **I**mplementation | Code under `src/` |

**Modes:**

- `/drift-check requirements` — session / recent commits vs `requirements.md`
- `/drift-check design` — MODULE.md + architecture ADRs vs `requirements.md`
- `/drift-check dev-full` — all modules' code vs their MODULE.md
- `/drift-check dev-module <name>` — one module vs its MODULE.md
- `/drift-check all` — R → D → I, with user approval at each descent

**Behavior:** each drift gets a per-item resolution prompt showing `file:line` evidence on both sides. The user picks direction — update layer A, update layer B, specify both, skip, or mark deferred. Never auto-decides; never auto-cascades.

**Deferred ≠ drift.** Each artifact has its own `## Deferred` section. Drift-check surfaces deferred items as one-line notes, not findings that need action.

**Soft nudge at close-session.** When a session touches multiple layers, `close-session` suggests a relevant drift-check mode. Non-blocking — `skip` to commit.

---

## MODULE.md schema

Per-module, co-located at `src/<module>/MODULE.md`:

```markdown
# <module>
**Purpose**        ← 1-2 sentences
**Public surface** ← signatures + trait/interface impls callers rely on
**Invariants**     ← threading, state, ordering guarantees
**Key choices**    ← each linked to DECISIONS.md by [D-XXX]
**Non-goals**      ← what this module deliberately DOESN'T do

<!-- BEGIN:STRUCTURE -->
... regenerated from code by regen-map ...
<!-- END:STRUCTURE -->

**Depends on** / **Depended on by**
```

Curated sections are hand-written (doc-first during architecture).

---

## DECISIONS.md conventions

- Sequential `D-XXX` IDs. Slug in heading.
- **Immutable entries.** To change a decision, add a new one; mark old as `Superseded by`.
- Entry fields: `Status`, `Date`, `Context`, `Decision`, `Why`, `Consequences`, optional `Alternatives`.
- **Filter for what to log:**
  - Reversing would cost >1 day
  - A reviewer would ask "why not X?"
  - Multiple options were considered
  - Affects module boundaries, public APIs, data shapes
  - Deliberate perf/correctness/security tradeoff
- **Don't log:** style choices, obvious defaults, bug fixes, trivial implementation details.

---

# Part 6 — Workflow

---

## First session — project init

You've just cloned a fresh repo with the skills scaffold.

```
You: (start new conversation in Claude Code or Cline)

Claude: [session-start fires; detects no phase files]
  "This project isn't fully initialized. Run /project-init? (yes/no)"

You: yes

Claude: [project-init runs]
  Interview (7 topics, answer in one batch):
  1. What we're building?
  2. How we're building? (stack + module convention)
  3. Stakeholder map & contribution surfaces?
  4. Domain constraints?
  5. LLM access model?
  6. Pain points?
  7. Artifact preferences?
```

---

## First session — after init

```
Claude: [writes files]
  ✓ docs/compact/phases/{requirements,architecture,development}.md
  ✓ docs/compact/PROJECT.md (skeleton)
  ✓ docs/compact/requirements.md (skeleton — FR / NFR / Deferred)
  ✓ docs/compact/STATUS.md (active phase: requirements)
  ✓ docs/compact/DECISIONS.md (empty)
  ✓ docs/compact/MAP.md (placeholder)
  ✓ docs/compact/structure-conventions.md (derived from stack)
  ✓ docs/compact/project-init-interview.md (your answers)

  "Initialized. Review structure-conventions.md — it's the AI's guess
   from your stack. Next step: /switch-phase requirements"
```

---

## Requirements phase

**Persona:** help user articulate *what*. Ask, don't design.

You and Claude iterate on two files:

- **`PROJECT.md`** — identity: who / why / scope boundaries. Who uses this? What's in scope for v1? What's out of scope? Contributors table.
- **`requirements.md`** — testable specs. Functional behaviors (`FR-1`, `FR-2`, …), non-functional constraints (`NFR-1`, `NFR-2`, …), and a Deferred section for postponed items.

Claude drives clarifying questions. You refine answers. IDs are stable — removed requirements are struck through in place, never renumbered.

**Exit criteria:** stakeholders agree on scope; open questions empty (or deferred); v1 FR set populated plus the NFRs the domain demands.

---

## Architecture phase

**Persona:** decide *how* at module level. No code yet.

You draft `src/<module>/MODULE.md` **doc-first**. For each module:
- Purpose
- Public surface (what callers can rely on)
- Invariants
- Non-goals (what we're NOT doing)
- Dependencies

Non-obvious choices become `DECISIONS.md` entries immediately.

**Exit criteria:** every planned module has a draft MODULE.md; dependency graph is acyclic (or cycles justified in a decision).

---

## Development phase

**Persona:** implement against the contracts you set in architecture.

You write code. Tests honor the invariants. When a decision emerges mid-code (non-trivial, not idiomatic), you capture it at session close.

**Golden rule:** if you feel tempted to change a curated section of `MODULE.md` (Public surface, Invariants, Non-goals) silently, **stop**. Switch back to architecture, revise intentionally, switch back.

`close-session` audits for this; it'll catch you if you forget.

---

## Session close ritual

Invoke `/close-session` before you stop:

1. **Recap** — you correct the AI's summary.
2. **STATUS update** — review diff, approve.
3. **Triage decisions** — numbered list; mark log/skip/unsure.
4. **Capture logged decisions** — plain-language Q&A.
5. **MODULE.md audit** — soft/hard flags on curated-section edits.
6. **Regen-map** — only if structure changed.
7. **Contribution drop-path scan** — surface new stakeholder artifacts (e.g. `contributions/eval/*.yaml`); route/defer/reject.
8. **Drift-check nudge** — soft, one-line suggestion if the session touched multiple R/D/I layers or drift-check is stale. `skip` to continue.
9. **Scaffold audit** — runs `/doctor` if any `.claude/skills/` files changed.
10. **Commit** — review full diff; commit / stage / abort.

**Never skip close-session.** It's where the memory gets made.

---

# Part 7 — Dry run: Shorty

A URL shortener. Small enough to see end-to-end.

---

## Dry run: setup

- Fresh repo, Rust stack.
- `.claude/skills/` copied from the shared scaffold.
- `CLAUDE.md` has: *"At the start of any new conversation, invoke the `session-start` skill."*

No `docs/compact/` yet. No code.

---

## Dry run: step 1 — init

```
Me: (opens new session)

Claude: [session-start detects uninitialized state]
  "Run /project-init?"

Me: yes

Claude: [7-topic interview]

Me: (answers)
  1. URL shortener; long URL → short code; redirect on GET.
  2. Rust, Axum, Tokio. In-memory storage v1.
  3. 2 engineers, peer review.
  4. No compliance. Public-facing eventually.
  5. Full LLM access.
  6. Pain: forgetting to update tests.
  7. Concise docs; ADR decisions.

Claude: [writes phase prompts + scaffolding]
  "Initialized. Next: /switch-phase requirements"
```

---

## Dry run: step 2 — requirements

```
Me: /switch-phase requirements

Claude: "Active phase: requirements. Persona: clarify what, not how.
         Two files get curated here:
           - PROJECT.md     — identity (who / why / scope boundaries)
           - requirements.md — behavioral specs (FR / NFR)"

Me: Let's start with PROJECT.md.

Claude: "Who are the users? What's out of scope for v1?
         Any non-goals worth stating up front?"

Me: (answers; iterates)

Claude: [drafts PROJECT.md — identity only]

Me: Now requirements.md.

Claude: "Walk me through each behavior; I'll assign FR-N / NFR-N."

Me: (POST /shorten, GET /<code>, latency target, single binary...)

Claude: [drafts requirements.md with FR-1..FR-N, NFR-1..NFR-N]
```

Result: `PROJECT.md` (identity) + `requirements.md` (testable specs). Split keeps identity stable while specs evolve.

---

## Dry run: step 2 — PROJECT.md result

```markdown
# Project: Shorty

*Identity: who / why / scope boundaries. Behavioral specs
live in requirements.md.*

**One-line**: Self-hostable URL shortener with in-memory
storage and HTTP API.

**Users**: Developers running internal tools or demos.

**In scope for v1**:
- URL shortening + redirect
- In-memory storage (single process)

**Out of scope**:
- Persistent storage (v2)
- Custom codes, expiration, analytics, auth

**Success criteria**: single binary; meets NFRs in requirements.md
```

---

## Dry run: step 2 — requirements.md result

```markdown
# Requirements

## Functional
- **FR-1** — POST /shorten accepts a long URL and returns
            a unique short code.
- **FR-2** — GET /<code> 301-redirects to the original URL.
- **FR-3** — Short codes are 7 chars, base62.

## Non-functional
- **NFR-1** — p99 redirect latency <100ms at 10K mappings.
- **NFR-2** — No code served before its mapping is stored.
- **NFR-3** — Single binary; no external deps at v1.

## Deferred
<!-- (none yet) -->
```

`/close-session`. STATUS updated. No decisions yet.

---

## Dry run: step 3 — architecture

```
Me: /switch-phase architecture
    Design module boundaries for Shorty.

Claude: "Proposed layout:
         - http   (Axum router, request handlers)
         - storage (in-memory HashMap behind RwLock)
         - idgen  (deterministic short code from URL hash)

         Shall I draft MODULE.md for each?"

Me: yes.

Claude: [drafts 3 MODULE.md files, doc-first]
        [drafts 3 DECISIONS entries: Axum>Actix, HashMap+RwLock,
         deterministic 7-char base62]
```

---

## Dry run: step 3 — MODULE.md result

`src/storage/MODULE.md`:

```markdown
# storage
**Purpose**: persist short→long URL mappings; read-heavy.
**Public surface**:
- `Store::new() -> Store`
- `put(short, long) -> Result<(), Collision>`
- `get(short) -> Option<String>`
**Invariants**:
- Thread-safe under concurrent reads.
- Codes immutable once set.
**Key choices**:
- HashMap + RwLock, not DashMap — [D-002](…#d-002)
**Non-goals**:
- No disk persistence
- No TTL
**Depends on**: none
**Depended on by**: http
```

---

## Dry run: step 4 — development (storage)

```
Me: /switch-phase development
    Implement storage per its MODULE.md.

Claude: [loads src/storage/MODULE.md]
        [writes Rust code]
```

Mid-implementation, Claude realizes `Store` needs `Clone` for Axum state. Adds `impl Clone`, wraps internals in `Arc`.

This changes the **Public surface** — callers can now rely on `Clone`. But it's idiomatic, not architectural.

---

## Dry run: step 5 — close-session

```
/close-session

Claude: [recaps: implemented storage; added Clone via Arc]

Me: matches my memory.

Claude: [STATUS update diff shown] ✓
        [decision triage: no decisions worth logging]
        [MODULE.md audit:
          storage/MODULE.md — SOFT FLAG
          impl Clone added to Public surface
          Options: decision / accept-idiomatic / revert]

Me: accept-idiomatic (add to Public surface, no DECISIONS entry)

Claude: [regen-map runs because Inner struct added]
        [self-check passes — only Structure touched]
        [commit message drafted]
```

---

## Dry run: what it proved

- Phases carried real weight. Requirements made `PROJECT.md`; architecture made `MODULE.md` + decisions; development made code.
- `regen-map` stayed safely in its lane.
- `close-session`'s audit **caught** the Public-surface expansion. Soft-flag let us accept it without ceremony.
- Every change was diff-reviewed before committing.

Total: ~3 sessions for a small feature, end-to-end. Every artifact was reviewable.

---

# Part 8 — Using this in both tools

---

## Dual-tool design — recap

This system is **identically usable in Claude Code and Cline**. The scaffold is the same; only the invocation surface differs.

| Aspect | Claude Code | Cline |
|---|---|---|
| Scaffold location | `.claude/skills/` | `.claude/skills/` (same) |
| Skill file format | `SKILL.md` (YAML frontmatter + body) | Same |
| Auto-trigger file | `CLAUDE.md` | `.clinerules` |
| Skill invocation | `/skill-name args` | `@skill-name args` or chat request |
| Diff review UI | Terminal inline diff | VS Code diff panel |
| LLM backing | Anthropic Claude | Internal 200B+ reasoning LLM |

Everything downstream — markdown files, workflow, rituals — is identical.

---

## Why both tools

- **Claude Code** — personal machines, Anthropic's hosted Claude. Fast iteration, latest model capabilities.
- **Cline** — work machines, our internal LLM. Sensitive code never leaves the network; reasoning model handles architecture-phase thinking well.

The system is built so **switching tools doesn't mean switching workflow**. A project initialized in Claude Code at home is fully usable in Cline at work the next morning.

Goal: one scaffold that travels with you.

---

## Setup on Claude Code

1. Install Claude Code (`npm install -g @anthropic-ai/claude-code` or see docs).
2. Authenticate: `claude login`.
3. In your project repo:
   ```bash
   cp -r /path/to/shared/skills/compact/. .claude/skills/
   ```
4. Add to `CLAUDE.md` at repo root (create if missing):
   ```
   At the start of any new conversation, invoke the
   session-start skill. If the conversation has been
   auto-compacted since the last session-start, re-invoke
   it before continuing work.
   ```
5. Start a session: `claude` in the repo. `session-start` fires; `/project-init` if uninitialized.

That's it. You're in the workflow.

---

## Setup on Cline — installing the extension

1. Open VS Code.
2. Extensions panel → search **"Cline"** → Install.
3. Open the Cline panel (left activity bar).
4. Click the settings gear.
5. Configure the model provider:
   - **Provider**: OpenAI Compatible (or your team's configured provider)
   - **Base URL**: `<internal LLM endpoint from team secrets>`
   - **API Key**: from team secrets manager
   - **Model ID**: `<your team's model name>`
   - **Thinking / reasoning**: enable if the model supports it (ours does)
6. Verify: open Cline chat, type `hello` — confirm you get a response.

---

## Setup on Cline — project configuration

Same skills scaffold copy as Claude Code:

```bash
cp -r /path/to/shared/skills/compact/. .claude/skills/
```

Create **`.clinerules`** at the project root (Cline's equivalent of `CLAUDE.md`):

```
At the start of any new conversation, invoke the session-start skill.
For long sessions, re-invoke session-start any time context feels
stale so Tier 1 state is reloaded from disk.

Skills live in .claude/skills/<skill-name>/SKILL.md. Read the SKILL.md
to understand how to invoke each skill. Available skills:
  - compact, session-start, switch-phase, close-session,
    regen-map, drift-check, project-init, doctor
```

Cline reads `.clinerules` when a conversation starts. No other config needed. Cline doesn't auto-compact, so the re-invocation is manual when the team spots staleness (model referring to files by recall instead of re-reading).

---

## Invoking skills in Cline

Cline doesn't have Claude Code's native `/slash-command` shortcut, so skills are invoked by **natural request** or `@mention`:

| Action | Claude Code | Cline |
|---|---|---|
| Start session | Auto (via `CLAUDE.md`) | Auto (via `.clinerules`) |
| Orientation / refresher | `/compact` | `run the compact skill` |
| Init project | `/project-init` | `run the project-init skill` |
| Switch phase | `/switch-phase architecture` | `run the switch-phase skill with arg architecture` |
| Close session | `/close-session` | `run the close-session skill` |
| Regen map | `/regen-map` | `run the regen-map skill` |
| Drift check | `/drift-check <mode>` | `run the drift-check skill with arg <mode>` |
| Audit scaffold | `/doctor` | `run the doctor skill` |

Cline reads the matching `SKILL.md` and follows it identically. The experience is the same; only the command form differs.

---

## Reviewing diffs in Cline

Cline integrates with VS Code's diff viewer — *visually richer* than Claude Code's terminal diff.

When `close-session` proposes a change:
- Cline opens the file with an **inline diff** in the editor.
- Approve / reject **per hunk** using the accept/reject buttons.
- Rejected hunks are dropped; approved hunks are saved.

**Recommended Cline settings** for our workflow:

- **Auto-approve reads**: on (safe).
- **Auto-approve writes in `docs/compact/`**: **off**. Every memory-file edit should be human-reviewed. That's the whole point of the system.
- **Auto-approve code writes**: off initially; loosen as trust builds.

---

## Cline gotchas — things to know

- **Context window**: the internal LLM has its own limits. Tier 1 progressive loading keeps us well under, but watch phase-file size if you customize heavily.
- **Thinking mode**: leave reasoning **on** for architecture and development phases. The think-time pays for itself on design work.
- **`.clineignore`**: works like `.gitignore`. **Do not** add `docs/compact/` or `MODULE.md` to it — Cline needs to see them to hydrate context.
- **Workspace state**: Cline keeps chat history per workspace. If you reuse a workspace for a different project, clear history first to avoid cross-project contamination.
- **`.clinerules` precedence**: team-level `.clinerules` in the repo overrides any global user rules. That's what we want — project shapes behavior, not user setup.

---

## Long sessions — handling auto-compaction

Claude Code auto-summarizes earlier portions of a conversation as it nears the context limit. The summary keeps intent; it can lose specific file contents. COMPACT is designed so this is largely harmless — authoritative state lives on disk (`PROJECT.md`, `STATUS.md`, `DECISIONS.md`, `MAP.md`, active phase file, `MODULE.md`s). What compaction loses, a re-read restores.

Three team habits keep sessions clean:

1. **Re-invoke `session-start` after auto-compaction or when context feels stale.** It's idempotent and cheap; reloads Tier 1 from disk. Trust files over model recall.
2. **Checkpoint often with `close-session`.** Progress captured into `STATUS.md` + `DECISIONS.md` survives any later compaction.
3. **Ask the AI to re-read before acting on specifics.** *"Re-read `src/<module>/MODULE.md` before you propose that change."*

Cline doesn't auto-compact, so habits 1-3 are team ritual. Claude Code users can automate the reminder with a `PreCompact` hook in `.claude/settings.json` — see README's "Long sessions and auto-compaction" section for the snippet.

---

## Keeping the two tools in sync

The repo is the source of truth. Both tools read the same files.

- **Skills updates**: when the shared scaffold changes, copy again into `.claude/skills/`. Both tools pick it up next session.
- **Phase prompt tweaks**: edit `docs/compact/phases/*.md`. Applies identically in both tools.
- **Model differences**: don't paper over them. If Claude Code produces one style and Cline another, capture it in `structure-conventions.md` or as a DECISION; don't fork the system.

**Rule of thumb**: if a fix only works in one tool, the fix is wrong. The scaffold should be tool-agnostic.

---

# Part 9 — Getting started

---

## Setup checklist (per new project)

1. Clone/create the project repo.
2. Copy the skills scaffold:
   ```bash
   cp -r /path/to/shared/skills/compact/. .claude/skills/
   ```
3. **Claude Code users**: create `CLAUDE.md` at repo root with:
   ```
   At the start of any new conversation, invoke the
   session-start skill.
   ```
4. **Cline users**: create `.clinerules` at repo root with the same line (plus the skills discovery hint from Part 8).
5. Open a new conversation in your tool. `session-start` fires; `/project-init` (or `run the project-init skill` in Cline) guides you.
6. You're ready to `/switch-phase requirements`.

Both files (`CLAUDE.md`, `.clinerules`) can coexist in the same repo — harmless, and lets teammates use either tool.

---

## First-day checklist (for team members)

- [ ] Read this deck.
- [ ] Install your tool: Claude Code (personal) **and/or** Cline (work).
- [ ] Read one project's `docs/compact/` end-to-end.
- [ ] Open a conversation, let `session-start` brief you.
- [ ] Practice `switch-phase` and `close-session` on a small task.
- [ ] If you use both tools: run the same session in Claude Code and Cline — confirm the experience matches.
- [ ] Review one existing `DECISIONS.md` entry and trace it to its MODULE.md.
- [ ] Ask questions. The system evolves from real use.

---

## FAQ

**Q: Do I have to run `session-start` every time?**
A: It fires automatically via the CLAUDE.md one-liner. If you skip it, you lose context hydration.

**Q: What if I forget `close-session`?**
A: Next session you'll see stale STATUS and possibly uncommitted `docs/compact/`. `session-start` flags both. No data loss, just friction.

**Q: What happens when Claude Code auto-compacts a long session?**
A: The authoritative state (`PROJECT.md`, `STATUS.md`, `DECISIONS.md`, `MODULE.md`, active phase) lives on disk and isn't affected — only conversation history gets summarized. Re-invoke `session-start` after compaction to reload Tier 1 from disk. Optionally add a `PreCompact` hook to `.claude/settings.json` for an automatic reminder (see README). Cline doesn't auto-compact; on long Cline sessions, re-invoke `session-start` whenever context feels stale.

**Q: Can I edit `MODULE.md` by hand?**
A: Yes — curated sections (Purpose, Public surface, Invariants, Key choices, Non-goals). Never the Structure section (regen-map owns it).

---

## FAQ continued

**Q: What if I disagree with a decision Claude recorded?**
A: Decisions are immutable. Add a new one marking the old as `Superseded by`. History stays intact.

**Q: How do I make sure requirements, design, and code stay aligned?**
A: `/drift-check` with a mode: `requirements`, `design`, `dev-full`, `dev-module <name>`, or `all` for a guided R→D→I cascade. Each mismatch is shown with `file:line` evidence on both sides; you pick the direction (update A, update B, specify both, skip, or mark deferred). Never auto-fixes. `close-session` emits a soft nudge when a session touched multiple layers — non-blocking, `skip` to commit.

**Q: What if the phase prompts don't fit my project's quirks?**
A: Run `/project-init --re-init`. Answers preserved as defaults; edit and regenerate.

**Q: Can I use this on an existing project?**
A: Yes — run `/project-init --retrofit`. It scans the codebase (languages, candidate modules, public-surface candidates per module), writes an archival `docs/compact/retrofit-snapshot.md`, seeds `MODULE.md` skeletons (each with a `<!-- retrofit: skeleton -->` sentinel), produces a polyglot-aware `structure-conventions.md`, optionally anchors observed choices as `reconstructed` DECISIONS entries, and runs `regen-map` once. Active phase lands at `architecture` — the team curates MODULE.md skeletons module-by-module and removes the sentinel as each becomes a real contract.

**Q: I already drafted a design doc in Claude web / ChatGPT / a doc tool. Can I bring it in?**
A: Yes — `/project-init` has a preflight that imports design artifacts into `docs/compact/design-inputs/`. The generated requirements + architecture phase prompts automatically reference them as starting proposals. You still go through all three phases, but the AI drafts PROJECT.md fields and candidate module boundaries from your inputs instead of starting blank. Reply `skip` at the preflight if greenfield.

**Q: What's the cost of all this ceremony?**
A: ~5-10 min of overhead per session. Payoff: codebase stays auditable, team stays in sync.

**Q: Do I need to commit to one tool?**
A: No. Use Claude Code for personal work, Cline for work machines. The scaffold and all artifacts are identical — a project started in one tool is fully usable in the other.

**Q: Cline isn't picking up my skills. What do I check?**
A: (1) Scaffold is at `.claude/skills/` not `.cline/skills/`. (2) `.clinerules` exists at repo root and mentions `session-start`. (3) `.clineignore` isn't excluding `.claude/` or `docs/compact/`. (4) Restart the Cline chat to re-read `.clinerules`.

---

## Feedback loop

This system is **v1**. Every failure mode we hit is data:

- Did the dry run flow feel clunky? Tell us where.
- Did `close-session` ask too many questions? Log it.
- Did a design choice slip past without getting captured? That's a filter bug.
- Did the skill instructions feel ambiguous? We'll tighten them.

**Iterate on the workflow, not just on code.**

---

## Summary

- **Three disciplines**: prompt, context, memory engineering.
- **One scaffold, two tools**: identical experience in Claude Code and Cline.
- **Three phases**: requirements, architecture, development — as lenses.
- **Two rituals**: session-start, close-session.
- **One rule**: propose, don't write. Everything is diff-reviewed.

If you remember nothing else: **the files in `docs/compact/` are the contract. Read them; edit them; review them in PRs — in whichever tool you're using.**

---

<!-- _class: lead -->
<!-- _paginate: false -->

# Questions?

---

## How to render this deck to PowerPoint

This file is **Marp** markdown. To produce a `.pptx`:

```bash
# install Marp CLI
npm install -g @marp-team/marp-cli

# render
marp COMPACT_Overview.md -o COMPACT_Overview.pptx

# or render to PDF / HTML
marp COMPACT_Overview.md -o COMPACT_Overview.pdf
marp COMPACT_Overview.md -o COMPACT_Overview.html
```

Or: open `COMPACT_Overview.md` in VS Code with the Marp extension for live preview.

The markdown source is the authoritative version — edit it, re-render when needed.
