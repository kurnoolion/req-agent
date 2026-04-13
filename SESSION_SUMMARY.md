# Session Summary: Telecom Requirements AI System Design

**Date:** April 11-13, 2026
**Purpose:** Feed this to Claude Code at the start of a new session to resume where we left off.

---

## Who You Are

You are my Applied AI Software Design Partner. We work collaboratively — structured decomposition before solutions, checkpoint-based progress, transparent reasoning, honest about uncertainty. Don't jump to code without aligning on design first. Push back when something doesn't look right.

I'm an AI solution architect with deep telecom domain expertise (3GPP, GSMA, US MNO device requirements).

---

## What We're Building

An AI system for intelligent querying, cross-referencing, and compliance analysis of US MNO (Verizon, AT&T, T-Mobile) device requirement specifications.

**Core architecture:** Knowledge Graph + RAG hybrid
- Graph scoping identifies WHERE to look (cross-doc, cross-MNO traversal)
- Targeted vector RAG ranks WHAT's most relevant within that scope
- Requirement hierarchy provides structural CONTEXT for LLM synthesis

**Why not pure RAG:** Already tried, failed. Can't handle cross-document dependencies, destroys hierarchical structure, misses standards context, no MNO/release awareness.

---

## Key Design Decisions Made

1. **KG + RAG over pure RAG** — graph is the routing layer, RAG does fine-grained ranking
2. **Graph scoping then targeted RAG** — not graph OR RAG, but graph THEN RAG within scoped candidate set
3. **Profile-driven structural parsing** — standalone DocumentProfiler derives document structure from representative docs (no LLM); generic structural parser applies the profile; LLM only for enrichment (concept tagging, relationship classification)
4. **Standards ingestion: Option C (Hybrid Selective)** — only ingest referenced 3GPP sections + surrounding context (parent, definitions, adjacent subsections), not full specs
5. **Bottom-up feature taxonomy** — derive from documents using LLM, then human review; not pre-defined
6. **Two cross-document patterns:** (a) Fragmented — one capability across multiple docs, handled by Feature nodes; (b) Dependent — requirement X needs requirement Y from another doc, handled by typed edges
7. **Four standards relationship types:** DEFER, CONSTRAIN, OVERRIDE, EXTEND — with pre-computed delta summaries
8. **Keep RAG** — don't skip to context stuffing even though context window may be large; production LLM context may be smaller
9. **Single unified graph + vector store** — not MxN partitioned; enables cross-MNO comparison and cross-release diff as natural traversals; shared standards and feature nodes
10. **DocumentProfiler + generic parser** — replaces per-MNO parser registry; DocumentProfiler is standalone, LLM-free, outputs human-editable JSON profile; generic parser applies profile to any MNO's docs; adding new MNO = profile representative docs, no code changes
11. **Test cases as first-class graph citizens** — separate parser, Test_Case nodes, tested_by/tests edges, doc_type metadata in vector store
12. **Release-specific standards versioning** — different MNOs may reference different 3GPP releases; separate Standard_Section nodes per release
13. **Multi-format support (PDF, DOC, DOCX, XLS, XLSX)** — format-aware extraction layer produces normalized intermediate representation; DOC converted to DOCX via LibreOffice headless; supports embedded OLE objects and images/diagrams
14. **Folder-structure-driven metadata** — `/<MNO>/<Release>/Requirements/`, `/<MNO>/<Release>/TestCases/`, `/Standards/<Spec>/<Release>/`

---

## Capabilities the System Must Support

### Requirement Q&A Bot
- Single-doc Q&A
- Cross-doc Q&A (query needs multiple requirement docs to answer)
- Cross-MNO comparison ("compare VZW vs TMO IMS registration")
- Standards comparison ("how does VZW differ from 3GPP for T3402?")
- Release diff / version comparison ("what changed in VZW eSIM from Oct 2025 to Feb 2026?")
- Traceability (requirement to test case mapping)

### Test Case Q&A
- Lookup test cases by requirement
- Test case content queries
- Test coverage analysis

### Compliance Agent (post-PoC)
- Single requirement compliance check against Excel compliance sheets
- Cross-document compliance consistency
- Auto-fill from module/chipset documentation
- Delta compliance sheet generation between releases

---

## Document Structure (VZW OA — analyzed from LTEDATARETRY.pdf)

- **Req ID format:** `VZ_REQ_{PLANID}_{NUMBER}` (e.g., VZ_REQ_LTEDATARETRY_7748)
- **Section hierarchy:** Up to 6+ levels (e.g., 1.4.3.1.1.10)
- **Every section IS a requirement** with its own VZ_REQ ID
- **Document zones:** 1.1-1.2 (meta), 1.3 (software specs/timers/algorithms), 1.4 (scenarios — bulk of requirements)
- **Cross-references:** 3GPP TS citations with section and release, other VZW plan names
- **Each doc references specific 3GPP release** (captured in Introduction/References section)
- **136 pages** for LTEDATARETRY alone

---

## Constraints

- **PoC:** Claude or Gemini API, personal PC, publicly available VZW docs only (5 PDFs in repo)
- **Production:** Proprietary on-premise LLM (supports thinking mode, context TBD maybe 2M), no external LLMs/cloud AI
- **Some flexibility** for open-source on-premise models
- **Scale:** PoC = 5 docs; Production = multiple MNOs x quarterly releases x hundreds of docs = GBs

---

## Design Document

The complete Technical Design Document is at `TDD_Telecom_Requirements_AI_System.md` (v0.4). It contains:
- Full architecture diagrams (ingestion + query pipelines)
- Detailed ingestion pipeline (7 stages including multi-format extraction)
- Knowledge graph model (8 node types, 15+ edge types)
- Query pipeline (6 stages including MNO/release resolution)
- All target capabilities with query flow examples
- PoC plan (11 steps, including DocumentProfiler) with evaluation criteria
- 15 identified risks with mitigations

---

## PoC Implementation Progress

### Completed Steps

#### PoC Step 1 — Document Content Extraction (DONE, committed)
- **Code:** `src/extraction/` (pdf_extractor.py, base.py, registry.py, extract.py)
- **Data model:** `src/models/document.py` — Normalized IR (DocumentIR, ContentBlock, FontInfo, Position, BlockType)
- **Output:** `data/extracted/*_ir.json` — 5 VZW docs extracted
- **Key design:** pymupdf for text+font metadata, pdfplumber for tables, table-region deduplication, font-group splitting for mixed-font blocks, header/footer filtering
- **Bugs fixed:** fitz_doc closed before page_count access, page numbers not filtered, degenerate TOC tables

#### PoC Step 2 — DocumentProfiler (DONE, committed)
- **Code:** `src/profiler/` (profiler.py, profile_schema.py, profile_cli.py)
- **Output:** `profiles/vzw_oa_profile.json` — VZW OA profile derived from LTEDATARETRY + LTEB13NAC
- **Validated** against 3 held-out docs (LTESMS, LTEAT, LTEOTADM) — all passed with 0 warnings
- **Key design:** Font size clustering for heading detection, regex mining for req IDs and metadata, frequency analysis for body text, zone classification by keyword matching
- **CLI:** `python -m src.profiler.profile_cli create|update|validate`

#### PoC Step 3 — Generic Structural Parser (IN PROGRESS, code complete, needs final validation + commit)
- **Code:** `src/parser/` (structural_parser.py, parse_cli.py)
- **Output:** `data/parsed/*_tree.json` — 5 VZW docs parsed into RequirementTree structures
- **Key classes:** GenericStructuralParser, RequirementTree, Requirement, CrossReferences, StandardsRef, TableData, ImageRef
- **Parser run results (after fixes):**
  | Document | Requirements | Standards Releases | Sections w/ Cross-Refs | Internal Refs | External Plan Refs | Standards Citations |
  |---|---|---|---|---|---|---|
  | LTEAT | 16 | 0 | 6 | 6 | 0 | 14 |
  | LTEB13NAC | 431 | 50 | 116 | 285 | 1 | 261 |
  | LTEDATARETRY | 115 | 18 | 43 | 73 | 0 | 62 |
  | LTEOTADM | 80 | 0 | 3 | 65 | 3 | 2 |
  | LTESMS | 69 | 9 | 8 | 10 | 0 | 16 |
- **Bugs fixed during Step 3:**
  1. `_extract_standards_releases()` — added bidirectional pattern (VZW docs use "Release N version of 3GPP TS X.X" in addition to standard order)
  2. `_extract_cross_refs()` — added spec-only standards reference detection (many refs cite spec without section number)
- **Minor data quality issue noticed (not yet fixed):** Some spec names have trailing dots (e.g., `3GPP TS 36.306.` instead of `3GPP TS 36.306`) — likely from source PDF text extraction artifacts
- **CLI:** `python -m src.parser.parse_cli --profile <profile> --doc <ir.json> --output <tree.json>`

### Remaining Steps

4. Test case parsing (separate parser for test case documents)
5. Cross-reference extraction (resolve references between parsed requirement trees)
6. Feature taxonomy (LLM-driven concept extraction from parsed requirements)
7. Standards ingestion (3GPP spec parsing, selective section extraction)
8. Knowledge Graph construction (Neo4j or similar)
9. Vector store (embeddings for parsed requirement text)
10. Query pipeline (graph scoping + RAG ranking + LLM synthesis)
11. Evaluation (accuracy, coverage, latency benchmarks)

---

## Where We Left Off

**Status:** PoC Step 3 nearly complete.

**What just happened:**
- Re-ran the parser on all 5 VZW docs with the two fixes (standards releases + cross-refs) — results look good (see table above)
- Noticed a minor data quality issue: trailing dots in some spec names (`3GPP TS 36.306.`) — likely from PDF text artifacts. Was about to investigate/fix when session ended.

**Immediate next actions:**
1. Fix trailing-dot spec name issue in `_extract_standards_releases()` in `src/parser/structural_parser.py`
2. Re-run parser one final time to confirm clean output
3. Commit PoC Step 3
4. Move to PoC Step 4

---

## Project File Structure

```
req-agent/
├── CLAUDE.md                          # Claude Code instructions
├── SESSION_SUMMARY.md                 # This file
├── TDD_Telecom_Requirements_AI_System.md  # Full technical design (v0.4)
├── requirements.txt                   # Python dependencies
├── profiles/
│   └── vzw_oa_profile.json           # VZW OA document profile
├── src/
│   ├── models/
│   │   └── document.py               # Normalized IR data model
│   ├── extraction/
│   │   ├── base.py                   # Abstract extractor
│   │   ├── pdf_extractor.py          # PDF extraction (pymupdf + pdfplumber)
│   │   ├── registry.py               # Extractor registry + path metadata
│   │   └── extract.py                # Extraction CLI
│   ├── profiler/
│   │   ├── profile_schema.py         # Profile data model
│   │   ├── profiler.py               # DocumentProfiler (heuristic analysis)
│   │   └── profile_cli.py            # Profiler CLI
│   └── parser/
│       ├── structural_parser.py      # GenericStructuralParser (profile-driven)
│       └── parse_cli.py              # Parser CLI
├── data/
│   ├── extracted/                    # IR JSON files (5 docs)
│   └── parsed/                       # RequirementTree JSON files (5 docs)
└── VZW/Feb2026/Requirements/         # Source PDFs (5 VZW OA docs)
```

---

## Memory Files

The design decisions, project context, VZW document structure analysis, and collaboration preferences are saved in Claude Code's memory system. They should auto-load in a new session if the working directory path is the same. If the directory was renamed, tell Claude to check `SESSION_SUMMARY.md` and `TDD_Telecom_Requirements_AI_System.md` for full context.
