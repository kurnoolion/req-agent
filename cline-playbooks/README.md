# Cline playbooks

These are the structured tasks the user invokes against the on-prem corpus. Each playbook
is self-contained: a brief, the steps, the report template.

The always-on rules in `.clinerules/` (loaded automatically) govern Cline's role,
content-safety / redaction protocol, and output discipline. The playbooks here are invoked
**manually** per task.

## How to invoke

In your Cline conversation, paste the playbook path and the input:

> *"Follow `cline-playbooks/profile-corpus.md` for `<env_dir>/input/<MNO>/<RELEASE>/<plan>.pdf`."*

Cline reads the playbook and executes the steps.

## Playbooks

| File | Purpose | Output |
|---|---|---|
| [`orient.md`](orient.md) | Load NORA's project context (run on first conversation per session) | `ORIENT` report (~5–8 lines) |
| [`mapping.md`](mapping.md) | Maintain the redaction table at `<env_dir>/state/cline-mapping.json` | `MAP` report (~2–4 lines) |
| [`profile-corpus.md`](profile-corpus.md) | Profile one document; capture format patterns | `PROF` report (~12–15 lines) |
| [`derive-rule.md`](derive-rule.md) | Build a detection rule for one structural element | `RULE` report (~8–10 lines) |
| [`debug-pipeline.md`](debug-pipeline.md) | Run pipeline stages, capture stats | `RPT` report (~15–25 lines) |
| [`share-back.md`](share-back.md) | Bundle multiple reports for one typing trip | `BUNDLE` report (≤40 lines) |

## Workflow loop

```
   ┌──── on-prem (Cline + corpus) ──┐               ┌──── cloud (Teacher LLM) ────┐
   │                                │   manual      │                        │
   │  1. user invokes a playbook    │   typing      │  3. read report        │
   │  2. Cline produces compact     │ ───────────▶  │  4. design + code      │
   │     redacted report            │               │  5. commit to git      │
   │  6. user runs `git pull`       │ ◀──── git ──── │                        │
   │  7. Cline runs new code        │               │                        │
   │  8. Cline reports follow-up    │ ───────────▶  │  9. respond            │
   └────────────────────────────────┘               └────────────────────────┘
```

Steps 3 + 9 ("read") are manual — the user types the redacted report from Cline's screen
into Teacher LLM. Code never moves through chat — only through git.

## Per-session bootstrap

Run `orient.md` first each session. Then proceed to the task.

## Adding new playbooks

When a recurring on-prem task emerges that doesn't fit any existing playbook:

1. Capture the steps once with the user (manually).
2. If the same shape repeats 3+ times, ask Teacher LLM to draft a playbook file.
3. Commit to `cline-playbooks/`.
4. Add the row to the table above.
