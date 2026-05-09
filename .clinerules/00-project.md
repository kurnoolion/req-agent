# NORA project context

This repo is **NORA — Network Operator Requirements Analyzer**. Python codebase that
ingests US MNO device-requirement specs, builds a knowledge graph + targeted RAG vector
store, and answers questions with grounded citations. Active phase: development.

Where to read more (in this order, on first run via the `orient` playbook):
- `docs/compact/PROJECT.md` — 1-page identity + Contributors table
- `docs/compact/MAP.md` — module table + Mermaid dependency graph
- `docs/compact/STATUS.md` — active phase, in-progress, flags
- `docs/compact/requirements.md` — FR/NFR (load only when explicitly working on requirements)
- `core/src/<module>/MODULE.md` — per-module curated contracts (load on demand)
- `core/src/query/RETRIEVAL.md` — retrieval pipeline reference

The project is partnered between a **Teacher LLM** (full design + code) and you
(on-prem Cline, the student with corpus access). Your role and content-safety rules are
in `01-role.md` / `02-content-safety.md`.

The existing `docs/compact/` scaffold is a separate methodology (COMPACT) that Teacher LLM uses
to maintain project context across sessions. You do not invoke COMPACT skills; you
read the artifacts COMPACT produced.
