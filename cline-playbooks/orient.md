# Playbook: orient

**Purpose**: load NORA's project context. Run on the first conversation each session, OR
when context feels stale.

**Input**: optionally a module name (e.g., `query`, `parser`, `vectorstore`).

## Steps

1. Read `docs/compact/PROJECT.md` — 1-page identity, Contributors table.
2. Read `docs/compact/STATUS.md` — active phase, in-progress, flags.
3. Read `docs/compact/MAP.md` (module table only — skim the diagram, don't load it deep).
4. Skim `core/src/query/RETRIEVAL.md` table of contents — note section numbers but don't
   load the body.
5. If the user named a module, read `core/src/<module>/MODULE.md`.
6. If `<env_dir>/state/cline-mapping.json` exists, read it so you know the redaction table
   for this session. If it doesn't exist, note that — running `mapping.md` is the next step.

Do **NOT** load (Tier 2 — only on demand by an explicit task):

- `docs/compact/DECISIONS.md`
- Any other module's `MODULE.md`
- `docs/compact/requirements.md`

Target budget: keep loaded context under ~5K tokens.

## Output: `ORIENT` report shape

```
ORIENT v=1
phase: <active phase>
in_progress: <count>
next: <count>
flags: <count>
mapping: v=<N> entries=<N> [or "absent — run mapping.md"]
ready: yes [or "stale: <reason>"]
```

If staleness was detected (in-progress items >7 days old, non-empty flags from prior
sessions), append the reason concisely.

## Constraints

- **Maximum 8 lines** in the output.
- No prose explanation of "what NORA is" — Teacher LLM already knows; the user already knows.
  This report is a status check, not an introduction.
