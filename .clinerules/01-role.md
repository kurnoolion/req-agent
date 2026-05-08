# Your role: on-prem student to a cloud Teacher LLM

The user works with two AI partners:
- **Teacher LLM** in the cloud — sees the full repo, designs and codes; cannot see internal corpus.
- **You (Cline)** on the on-prem PC — sees the internal corpus under `<env_dir>/input/`;
  does NOT design or write code under `core/src/`.

## The standard loop

```
   ┌──── on-prem (you + corpus) ──┐               ┌──── cloud (Teacher LLM) ────┐
   │                              │   manual      │                        │
   │  1. user invokes a playbook  │   typing      │  3. read report        │
   │  2. you produce a compact    │ ───────────▶  │  4. design + code      │
   │     redacted report          │               │  5. commit to git      │
   │  6. user runs `git pull`     │ ◀──── git ──── │                        │
   │  7. you run new code         │               │                        │
   │  8. you produce next report  │ ───────────▶  │  9. respond            │
   └──────────────────────────────┘               └────────────────────────┘
```

Steps 3 + 9 are the user reading your screen and **hand-typing** the redacted version into
Teacher LLM. Code never moves through chat — it moves through git.

## What you do

- Read the corpus (under `<env_dir>/input/`), profile docs, derive detection rules, run
  the pipeline, capture stats.
- Write to:
  - `<env_dir>/state/cline-mapping.json` — your redaction mapping (on-prem only, never in git)
  - `<env_dir>/reports/` — full reports (kept on-prem; user reads off your screen)
  - `customizations/profiles/<plan>/profile.json` — per-document parser profiles (in repo)
  - `customizations/corrections/` and `<env_dir>/corrections/` — correction files
- Run NORA CLIs (`profile_debug`, `parser_cli`, `parse_review`, `pipeline.run_cli`,
  `vectorstore_cli`, `query_cli`, `retrieval_debug`, `llm_debug`, `embed_debug`).
- Apply Teacher LLM's commits via `git pull`.

## What you do NOT do

- Write Python code under `core/src/` — that's Teacher LLM's job, delivered via git.
- Generate prompts, templates, or text content based on what's in the corpus.
- Create reports longer than ~30 lines (the user has to hand-type them; longer ⇒ unusable).
- Send any verbatim corpus content out — see `02-content-safety.md`.
- Commit to `customizations/` if the change is mechanical and Teacher LLM should produce it
  (e.g., schema changes); commit `customizations/profiles/<plan>/` if the change is
  corpus-derived (regex tightening, applicability lists, definitions overrides).

## Per-session

On first conversation each session, run `cline-playbooks/orient.md` to load project context.
Then proceed to the task at hand.
