# Retrieval Pipeline — Design

This document is the architectural reference for NORA's online
retrieval path. It covers every layer between the raw user query
and the chunks handed to the LLM synthesizer, with the rationale
for each layer and pointers to the ADRs that pinned the design.

> **Audience.** Engineers tuning retrieval, evaluating new
> reranking / fusion techniques, or debugging why a particular
> chunk did or didn't surface in a given answer. For the higher-
> level system view see [`docs/compact/PROJECT.md`](../../../docs/compact/PROJECT.md);
> for the public API surface see [`MODULE.md`](MODULE.md).

## 1. Pipeline shape

The query pipeline (`pipeline.QueryPipeline.query`) is six numbered
stages plus three intermediate sub-stages added by feature work
(decimals — slot between integers without renumbering). Every stage
is replaceable by injection.

```
                +-----------------------------------------------------+
  raw query --> | 1.   analyzer     -> QueryIntent                    |
                | 2.   resolver     -> ScopedQuery                    |
                | 3.   graph_scope  -> CandidateSet            ──┐    |
                | 3.5. rewriter     -> retrieval_query           │    |  query rewriting
                | 4.   retriever    -> [RetrievedChunk]          │    |  BM25 + dense + RRF
                | 4.5. threshold    -> filter / not-found        │    |  D-047 — drop weak chunks
                | 4.7. grouping     -> auto-commit / disambig    │    |  D-049 — cluster by path
                | 5.   context      -> AssembledContext          │    |
                | 6.   synthesizer  -> QueryResponse             ◄────┘
                | 6.5. citation_audit -> per-sentence audit           |  D-052 — flag uncited / fabricated
                +-----------------------------------------------------+
```

Decimal numbering convention: the 0.5/0.7 markers indicate "between
the integer-numbered stages." 4.5 runs after RAG (4) and before
synthesis-related work; 4.7 runs after the threshold filter. The
0.7 (vs 0.6) leaves room for a future Stage 4.6 if something needs
to slot in between.

### What's tunable, what's contract

**Contract** (architectural commitments, in ADR-anchored order):

- D-001 — `graph routes / RAG ranks`. Vector retrieval is always
  filtered by the graph's `CandidateSet`, never unscoped. Exception:
  RAG-only mode (`_bypass_graph=True`) when the graph stage was
  deliberately skipped.
- Stage signatures are typed dataclasses; each stage's output is
  the next stage's only input. No stage reaches back for state.
- Every stage injectable; mocks (`MockQueryAnalyzer`, `MockSynthesizer`,
  `MockReranker`, `MockQueryRewriter`) exist so the pipeline runs
  without any LLM for offline debugging.
- D-046 — every chunk's metadata carries `hierarchy_path: list[str]`
  with the document name (`plan_name` or `plan_id`) as the root.
  This is the input grouping (§11) reads. Older vectorstores
  without it degrade gracefully; rebuild required for full benefit.
- D-049 — when retrieval can't distinguish between plausible
  groups (gap below threshold), the pipeline returns disambiguation,
  not a synthesized "best guess." Codifies "the system shall not
  pretend it is an Oracle."

**Tunable** (per-query-type policy maps in `pipeline.py`, plus
config-resolved scalars). Each one is empirical — values shift as
the eval set grows or new corpora arrive:

| Knob | Where | Driven by |
|---|---|---|
| `_TYPE_TOP_K` | `pipeline.py` | per-query-type breadth widening (D-040) |
| `_TYPE_BM25_WEIGHT` | `pipeline.py` + `bm25_weight_by_type` in `config/retrieval.json` | per-type table editor on /config (D-053) |
| `_TYPE_REWRITE_ENABLED` | `pipeline.py` | per-type Stage-3.5 gate |
| `_TYPE_RERANK_ENABLED` | `pipeline.py` | per-type cross-encoder gate |
| `_TYPE_MAX_DISTANCE` | `pipeline.py` | per-type Stage-4.5 floor (D-047 + D-051) |
| `_TYPE_DISABLE_GROUPING` | `pipeline.py` | per-type Stage-4.7 opt-out (D-049 + D-051) |
| `enable_grouping` | `config/retrieval.json` | Stage 4.7 master toggle |
| `gap_threshold` | `config/retrieval.json` | Stage 4.7 auto-commit cutoff |
| `top_k_cap` | `config/retrieval.json` (via DB) | hard ceiling AFTER per-type widening |
| `max_distance_threshold` | `NORA_MAX_DISTANCE_THRESHOLD` env / DB | Stage 4.5 default cap |

§§10–14 below describe the new stages and the configuration model
that surfaces these knobs through the resolver chain
(CLI > env > DB > config/*.json > defaults; D-050 + D-053).

## 2. Graph scoping (Stage 3)

`GraphScoper` produces the `CandidateSet` that gates Stage 4.
Three lookup paths run in parallel and merge:

| Path | Trigger | Purpose |
|---|---|---|
| `_entity_lookup` | analyzer extracted `req:*` IDs that exist as graph nodes | Authoritative anchor |
| `_feature_lookup` | analyzer extracted feature names | Topical breadth |
| `_plan_lookup` | analyzer extracted plan IDs | Document-level breadth |
| `_title_search` | concepts/entities matched in node titles/text | Recall fallback |

### Entity-priority shortcut (D-039)

When `_entity_lookup` matches, the other three paths are **skipped**.
This was a real fix: a query like *"What is VZ\_REQ\_LTEDATARETRY\_200?"*
matched the entity AND triggered `_feature_lookup` on
DATA\_RETRY, which expanded the candidate scope from 1 req to
~700. Vector ranking inside a 700-req scope drowned the named
chunk.

Edge traversal still runs from the entity seed, providing the
immediate neighborhood (siblings, referenced standards, parent
container). The named-req anchor is preserved without losing
useful context.

## 3. Query rewriting (Stage 3.5)

`pre-retrieval expansion`. Off by default for `SINGLE_DOC` and
`GENERAL`; on for the other types via `_TYPE_REWRITE_ENABLED`.

- `MockQueryRewriter` (default) — returns `[]`, no-op.
- `LLMQueryRewriter` — generates 3 short paraphrases (5–15
  words, same scope) using the configured LLM. The original query
  + paraphrases are concatenated for embedding/BM25.

**Why per-type**: SINGLE\_DOC entity lookups already work via
D-039; rewriting injects telecom terminology that helps concept-
shaped queries (CROSS\_DOC, STANDARDS\_COMPARISON, FEATURE\_LEVEL)
find chunks the user's exact wording missed. The rewriter
prompt was tightened from "list corpus topics" (which polluted
every rewrite with LTE/IMS/SMS/etc.) to "5–15 words, same scope"
after the first version diluted retrieval.

## 4. Hybrid retrieval (Stage 4) — D-041

Two retrievers run in parallel, fused via Reciprocal Rank Fusion
(RRF, Cormack 2009):

### 4.1 Dense

Standard vector similarity over the Chroma store. Filtered by
`metadata.req_id $in candidate_req_ids` when the candidate set is
non-empty; otherwise filtered by MNO/release.

### 4.2 Sparse — BM25 (`bm25_index.py`)

- `BM25Index` wraps `rank_bm25.BM25Okapi` with its own
  `(id, text, metadata)` cache.
- Telecom-aware tokenizer preserves req IDs (`vz_req_lteat_45`),
  spec numbers (`24.301`), release codes (`rel-9`) as single
  tokens. Lower-cased. Stopwords retained (telecom abbreviations
  often look like stopwords — `at`, `it`, `is`).
- Built once per pipeline at construction time
  (`BM25Index.from_store(store)`); rebuild requires restart. The
  store fits in memory at present scale (~800 chunks, low MB);
  this becomes a knob if/when the corpus grows.

### 4.3 RRF fusion

`rrf_fuse(*lists, weights, k=60)`. Per-query-type BM25 weight
from `_TYPE_BM25_WEIGHT`:

```python
STANDARDS_COMPARISON = 0.5  # benefits — names specific TS / cause codes
TRACEABILITY         = 0.5  # benefits when query has specific terms
SINGLE_DOC           = 0.5  # entity-priority handles the well-formed case
CROSS_DOC            = 0.0  # parent chunks too thin to compete with BM25-favored leaves
FEATURE_LEVEL        = 0.0  # same as cross_doc
```

`weight = 0.0` short-circuits BM25 entirely (no index search runs).

**Why these values**: empirical tuning on the 18-question OA eval
set. STANDARDS\_COMPARISON gained +33pp accuracy with BM25 active.
CROSS\_DOC and FEATURE\_LEVEL regressed because parent/overview
chunks (heading-only) lose to richer leaf chunks pulled up by
BM25.

### 4.4 Per-query-type top\_k (D-040)

`_TYPE_TOP_K` widens to 25 for breadth-style queries (CROSS\_DOC,
FEATURE\_LEVEL, STANDARDS\_COMPARISON, CROSS\_MNO\_COMPARISON), 20
for TRACEABILITY / RELEASE\_DIFF, default 10 for lookups. The
expected hits in breadth categories often rank at #15+, so a
tight top\_k systematically misses them.

`QueryPipeline` takes `max(self._top_k, type_top_k)` so callers
can still raise the floor explicitly.

## 5. Cross-encoder reranker

`reranker.py`. Runs after RRF fusion, before diversity, on the
top-K\*2 pool. Default model: `cross-encoder/ms-marco-MiniLM-L6-v2`.

- `MockReranker` (default) — passthrough.
- `CrossEncoderReranker` — loads sentence-transformers
  CrossEncoder; degrades gracefully to passthrough if the model
  isn't cached or `sentence-transformers` is missing
  (`available=False`).
- Pre-call sort by descending score, stable on ties (preserves
  RRF order on equal-score chunks).
- Long chunks are truncated to `max_chunk_chars` (default 4000)
  before scoring to stay under the cross-encoder's token window.

`_TYPE_RERANK_ENABLED` enables reranking for the same query types
that benefit from wider top\_k. Off for SINGLE\_DOC (D-039 handles
it).

**Empirical caveat**: the off-the-shelf MiniLM cross-encoder is
trained on MS-MARCO web search and doesn't help (slight regression)
on technical spec text. Domain-tuned cross-encoder is the natural
next step. Code stays plumbed behind the flag.

## 6. Glossary lookup chain — D-043

The Test page surfaced a hallucinated answer for *"What is SDM?"*.
The fix was three layered changes:

### 6.1 Parser (`structural_parser._extract_definitions`)

The OA glossary table contained:

```
| ... | ... |
| SDM | Subscriber Device Management — APN management... |
| --- | --- |          ← stray divider
| UI  | User Interface |
| ... | ... |
```

Markdown extractors split this into two tables when the divider
appears mid-table; the SDM row landed in `tbl.headers`, not
`tbl.rows`. The original `_extract_definitions` only walked
`rows`, so SDM was silently dropped.

Fix: walk both `rows` AND `headers`. Filter the canonical
`Acronym | Definition` header via a token-set check — both
columns' headers must be entirely from a known canonical set
(`acronym, term, definition, abbreviation, …`) to be treated as
a real header.

VZW LTEOTADM `definitions_map`: 18 → 19 entries (SDM recovered).

### 6.2 Glossary chunks (`vectorstore.chunk_builder`)

Each entry in `definitions_map` becomes its own chunk:

- `chunk_id = "glossary:<plan_id>:<acronym-slug>"`
- `metadata.doc_type = "glossary_entry"`
- `metadata.{acronym, expansion}` populated for direct lookup.
- Text leads with `<ACRONYM>: <expansion>` so BM25 (high TF) and
  dense (concise definition) both rank it top for short acronym
  queries.

The whole acronym table also lives in the requirement chunk for
the definitions-section req. The glossary chunks are *additional*,
not replacement — short queries get high-precision answers, while
longer "show me the glossary" queries still hit the rich req
chunk.

### 6.3 Query-side pin (`rag_retriever`)

`_ACRONYM_QUERY_RE` matches:
- "What is X" / "What does X mean" / "What does X stand for"
- "Define X" / "Definition of X" / "Meaning of X"
- "Expand acronym X" / "Expand X"

`X` must be 2–15 chars, first char a letter, rest letters/digits/
dashes/underscores. Case-insensitive.

`RAGRetriever.__init__` builds `_glossary_by_acronym: dict[str,
list[RetrievedChunk]]` once by scanning `store.get_all()` for
`doc_type=glossary_entry` chunks. Empty on pre-D-043 corpora
(back-compat).

In `retrieve()`:
1. Run normal retrieval (graph scope → BM25+dense → rerank →
   diversity).
2. If `_detect_acronym_query(query)` returns `X` AND
   `X.lower() in _glossary_by_acronym`:
   - Prepend matched glossary chunks to the result.
   - Dedup by `chunk_id` (avoid double-listing if normal
     retrieval already pulled it).
   - Trim back to top\_k so downstream context budget is unchanged.

The pin runs **after** the cross-encoder so the encoder doesn't
demote a chunk we know is the answer. Pinned chunks carry
`similarity_score=1.0` by convention — they're hard-pinned, not
similarity-ranked.

### 6.4 Why three layers

Any one alone is insufficient:

- **Parser fix only** — `definitions_map` correct, but acronym
  query still loses to operational chunks. (Dense embedding
  treats "What is SDM?" similarly to any other 4-token query;
  BM25 rewards the chunk with the most "SDM" mentions, which
  isn't the glossary.)
- **Chunks only** — the glossary chunk is in the store but
  doesn't make top-K either, for the same ranking reason.
- **Pin only** — fires the regex, then can't find a chunk to
  pin to. Returns nothing useful.

The full chain ensures: (a) the acronym is *known* to the system,
(b) a *findable* chunk exists for it, and (c) acronym-shaped
queries *deterministically* surface it.

## 7. Diversity guard

`_enforce_diversity(chunks, k)` ensures at least
`diversity_min_per_plan` chunks come from each contributing plan.
This runs *after* fusion + rerank but *before* the glossary pin —
a glossary chunk is a single hard-pinned answer, not a diversity
contributor.

## 8. Acronym expansion in chunk text — D-032 / D-038

Independent of the glossary chunks (§6.2). At chunk-build time,
the first occurrence of each known acronym in *every* chunk is
expanded inline — `SDM` → `SDM (Subscriber Device Management)`.

- Per-document `definitions_map` only — `RAT` may mean different
  things in different MNO documents.
- Single-shot per chunk (subsequent occurrences keep the bare
  acronym so chunk text doesn't bloat).
- Skipped for chunks belonging to the definitions section
  itself (avoids double-anchoring).

This complements §6 by giving operational chunks (which mention
the acronym in passing) a co-occurring expansion, so a query that
phrased the question with the *expansion* still hits chunks that
only had the acronym, and vice versa.

## 9. End-to-end traversal: "What is SDM?"

Before D-043:

1. Analyzer → `SINGLE_DOC`, no entities.
2. Graph scope → falls through `_title_search`, returns ~50
   candidates that mention "SDM" anywhere.
3. Dense + BM25 → top-10 are operational chunks (ADD flow,
   OTADM, SMS).
4. Glossary chunk `req:VZ_REQ_LTEOTADM_2398` ranks #15-ish.
5. LLM has no real definition in context → invents
   "SIMOTA Device Management".

After D-043:

1. Analyzer → same.
2. Graph scope → same.
3. Dense + BM25 → same operational chunks.
4. Reranker → same.
5. **Glossary pin fires**: `_ACRONYM_QUERY_RE` matches "What is
   SDM?", `"sdm" in _glossary_by_acronym`, pin
   `glossary:LTEOTADM:SDM` to position 0.
6. LLM context contains `SDM: Subscriber Device Management — in
   this document, SDM refers to APN Management and Device
   "profiling".`
7. Answer is grounded.

## 10. Stage 4.5 — Relevance threshold filter (D-047)

After Stage 4 returns the top-K fused list, Stage 4.5 drops chunks
whose `similarity_score` (cosine distance) is above a threshold.
Lower distance = more similar.

```
chunks_in  ──> [c.similarity_score <= threshold] ──> chunks_out
                                                     │
                                                     │  if empty:
                                                     ▼
                                          QueryResponse(
                                              answer=_NOT_FOUND_ANSWER,
                                              ...
                                          )
                                                     │
                                                     ▼  Skip Stages 5/6
```

**Why a hard filter over "let the LLM judge"**: when retrieval
genuinely doesn't have the answer, passing weak chunks to the LLM
is the primary hallucination class. The model will dutifully
synthesize "based on the provided context..." prose from chunks
that scored 0.85 (cosine distance) — far from the query's
embedding — and the answer reads authoritative. Surfacing
`_NOT_FOUND_ANSWER` instead is more honest.

### Per-type threshold

`_TYPE_MAX_DISTANCE` overrides the pipeline-level default per
QueryType:

```python
_TYPE_MAX_DISTANCE = {
    QueryType.FACT:      0.4,   # strict — fact answer from weak chunks is worst-case
    QueryType.SUMMARIZE: 0.7,   # lenient — wants breadth, parent chunks score higher
}
```

Other types fall back to the pipeline-build-time
`max_distance_threshold` (constructor param, resolved from
`NORA_MAX_DISTANCE_THRESHOLD` env > ConfigStore >
`_DEFAULT_MAX_DISTANCE_THRESHOLD = 0.5`).

### Calibration

Threshold values are **embedding-model-specific.** From the in-
session sweep on env\_vzw + `qwen3-embedding:4b-q8_0`:

| Query category | Distance range |
|---|---|
| In-domain top-5 | 0.20 – 0.41 |
| Off-topic top-5 | 0.74 – 0.77 |

A 0.33-wide gap between worst-relevant and best-off-topic. The
default 0.5 sits comfortably in the middle. Different embedding
models will need re-tuning — see §15.3 (threshold sweep script).

### `_NOT_FOUND_ANSWER`

Deterministic message — same string every time, no LLM call:

> *No matching requirements were found in the indexed corpus for
> this query. The query may reference a topic, feature, or MNO
> release that is not yet ingested, or the phrasing may need to
> be adjusted. Try rephrasing, specifying an MNO/release, or
> checking which documents have been indexed.*

`QueryResponse.retrieved_count` is 0; citations list is empty.
The LLM never sees the context (saves the API call too).

## 11. Stage 4.7 — Hierarchy grouping + disambiguation (D-049)

Off by default; opt in via `enable_grouping=True` on the pipeline
constructor or `enable_grouping: true` in `config/retrieval.json`
(or `NORA_RETRIEVAL_GROUPING_ENABLED=1`).

When on and there are post-threshold chunks remaining, Stage 4.7:

1. **Clusters** chunks by **greedy longest-common-prefix (LCP)** on
   `metadata.hierarchy_path` (D-046). Sort chunks by path tuple
   (alphabetical, with `chunk_id` tiebreak); walk pairwise. Each
   chunk either extends the running group's LCP (when LCP ≥ 1
   element, i.e. shares the document root) or flushes the group
   and starts a new one.
2. **Scores each group** as `min(c.similarity_score for c in group)`.
   Best chunk anchors the group's relevance — weak siblings
   shouldn't drag.
3. **Sorts groups by score ascending** (best first).
4. **Decides**:
   - `len(groups) == 1` → pass through unchanged.
   - `len(groups) >= 2` AND `gap_between_top_groups(groups) >= gap_threshold`
     → **auto-commit** to top group. Other groups' chunks discarded
     before Stage 5.
   - `len(groups) >= 2` AND gap < threshold → **disambiguation**:
     return `QueryResponse(disambiguation_required=True, groups=[…])`,
     skipping Stages 5 and 6 (mirrors D-047's not-found short-circuit).

### Group score visualization

```
   group A: ["LTEOTADM"]                           score 0.21  ◄── auto-commit
   group B: ["LTEOTADM", "OTA-DM SPECIFICATIONS"]  score 0.45      gap 0.24
   group C: ["LTEDATARETRY"]                       score 0.48      ≥ 0.05
                                                                    ✓ pass
```

vs.

```
   group A: ["LTEOTADM"]      score 0.20  ◄── disambiguation
   group B: ["LTEDATARETRY"]  score 0.21      gap 0.01
   group C: ["LTEAT"]         score 0.22      < 0.05
                                              ✗ ambiguous
```

### Per-intent opt-out

Some intents inherently want **all** groups merged into one
synthesis pass — picking any single group throws away the breadth
the user is asking for. `_TYPE_DISABLE_GROUPING` lists those:

```python
_TYPE_DISABLE_GROUPING: set[QueryType] = {QueryType.SUMMARIZE}
```

When `intent.query_type ∈ _TYPE_DISABLE_GROUPING`, Stage 4.7 is
bypassed even when `enable_grouping=True` globally.

### Pinned-chunks path (Step 3c of D-049)

When the user picks a group from a disambiguation response (clicking
"Synthesize from this group" on the Test page), the web layer
re-issues the query with `QueryPipeline.query(query, pinned_chunk_ids=[…])`.
The pinned-chunks path:

1. Skips Stages 2 (resolver) → 4.7 (grouping) entirely.
2. Re-fetches the chunks from the store by ID via
   `_fetch_chunks_by_ids` (uses `store.get_all()` and filters in
   Python — O(n) on store size, acceptable at current scale).
3. Sets `similarity_score=0.0` on each fetched chunk (user
   explicitly picked them; no ranking).
4. Goes straight to Stage 5 (context assembly) and Stage 6 (synthesis).

Unknown IDs are dropped with a warning; if no IDs resolve, returns
`_NOT_FOUND_ANSWER`. Stage 1 (analyzer) still runs so Stage 5 has
the right system prompt for the original query's intent.

### `gap_threshold` calibration

Default `0.05`. Like the threshold filter, this is calibrated
per embedding model. Tighter (smaller) → more disambiguation
prompts; looser (larger) → more auto-commits. Per-type override
via `gap_threshold_by_type` in `config/retrieval.json`.

## 12. Intent-aware routing — FACT and SUMMARIZE (D-051)

Existing `QueryType` values classify queries by **scope shape**
(SINGLE_DOC, CROSS_DOC, FEATURE_LEVEL, etc. — how many docs the
answer spans). Two intent-shaped values were added in Step 4:

### FACT

Trigger phrases (analyzer.py): `value of`, `what value`,
`default value`, `default for`, `how many`, `how long`,
`maximum value`, `minimum value`, `exact value`, `specific value`,
`what is the limit`, `what is the threshold`.

Per-intent knobs:

| Knob | Value | Why |
|---|---|---|
| `top_k` | 10 | facts come from 1–3 chunks; widening adds noise |
| `bm25_weight` | 0.5 | timer names / cause codes are exact-token; BM25 wins |
| `rerank_enabled` | True | precision matters; reorder for the best match |
| `rewrite_enabled` | False | paraphrasing risks routing to the definitional path |
| `max_distance_threshold` | 0.4 | strict — fact-shaped answer from weak chunks is the worst hallucination class |
| Stage 4.7 grouping | enabled | one fact = one group, typically |

System prompt: *"Direct answer + per-sentence attribution +
explicit contradiction handling when sources disagree."*

### SUMMARIZE

Trigger phrases: `explain`, `summarize`, `summary of`,
`describe`, `give me an overview`, `overview of`, `tell me about`.

Per-intent knobs:

| Knob | Value | Why |
|---|---|---|
| `top_k` | 50 | wide — per-req chunks are small; breadth needs many |
| `bm25_weight` | 0.2 | mostly dense — user paraphrases the topic |
| `rerank_enabled` | False | cost vs benefit at top-50; LLM reads all anyway |
| `rewrite_enabled` | True | term expansion gathers more relevant chunks |
| `max_distance_threshold` | 0.7 | lenient — wants breadth incl. parent/overview chunks |
| Stage 4.7 grouping | **disabled** (`_TYPE_DISABLE_GROUPING`) | auto-commit-to-one-group throws away breadth |

System prompt: *"TL;DR (2–4 sentences) + per-section breakdown
grouped by document/section. Cite every requirement inline."*

### Classification priority

FACT is checked **before** SUMMARIZE so "Explain the value of
T3402" routes to FACT (precision) — the value-question shape
wins over the explain-shape when both phrasings appear.

Bare "What is X?" stays out of FACT — handled by the acronym
pin (§6) for definitional queries, or falls through to SINGLE\_DOC
/ GENERAL.

### Comparison intent — explicitly deferred

A `Comparison` intent for "Compare VZW and TMO authentication" /
"Compare Feb2025 vs June2025 for WiFi Calling" was scoped during
Step 4 but **not shipped** — needs multi-MNO / multi-release
ingestion to test against. Tracked in STATUS.md Next.

## 13. Stage 6.5 — Citation audit (D-052)

Always runs on the synthesis path (cheap regex, no LLM call).
Skipped on disambiguation / not-found paths (no real answer to audit).

```python
QueryResponse.citation_audit: CitationAudit | None
```

### What it detects

For each sentence in the answer:

1. **Cited?** — sentence contains a `(VZ_REQ_X_N)` token or a
   `3GPP TS X.Y, Section Z` reference.
2. **Fabricated?** — sentence cites a `VZ_REQ_X_N` that does NOT
   appear in `available_req_ids` (the chunks the LLM actually
   received). Worst-case error class: looks authoritative, isn't
   real. 3GPP citations are external and pass automatically.
3. **Meta?** — markdown headers (`# X`, `**X**`-only line),
   bare-label sentences (`Direct answer:`), blank lines. Marked
   `is_meta=True` and excluded from the cited-percentage metric.

### Sentence splitter

Regex-based, abbreviation-aware:

- Splits on `[.?!]` followed by whitespace + capital letter or
  end-of-line.
- Preserves `e.g.` / `i.e.` / `etc.` / `Sec.` / `Fig.` / etc. as
  in-sentence (substituted with a placeholder during the split,
  restored after).
- Bullet items (`- foo`, `* foo`, `1. foo`, `1) foo`) → each item
  is one sentence regardless of internal punctuation.
- Markdown headers passed through as their own sentence so they
  can be marked meta.

### Schema

```python
@dataclass
class SentenceAudit:
    text: str
    has_citation: bool
    citations_found: list[str]      # req IDs + 3GPP refs
    fabricated_citations: list[str] # req IDs not in available_req_ids
    is_meta: bool

@dataclass
class CitationAudit:
    sentences: list[SentenceAudit]
    cited_sentence_count: int
    factual_sentence_count: int    # total minus meta
    fabricated_count: int
    available_req_ids: list[str]
    cited_percent: float           # property
    uncited_sentences: list[SentenceAudit]  # property
```

### UI surfacing

The Test page (`templates/test/_answer.html`) renders an inline
summary: `4/6 sentences cited (66.7%) · 1 fabricated`. Below it,
collapsible "show uncited" list (yellow border) and a red alert
listing fabricated citations (lists the bad req IDs and the
sentence containing them).

### Phase 5c — repair pass deferred

A future "repair" pass would re-prompt the LLM with the
flagged uncited sentences asking it to add citations. Not shipped
yet — extra LLM call per query, cost-benefit unknown until real-
world miss rates are measured.

## 14. Configuration & tuning model (D-050, D-053)

Every retrieval knob flows through the same **5-tier resolution
chain**:

```
CLI flag > env var > ConfigStore (web DB) > config/*.json > defaults
```

### Layers, in order of precedence

1. **CLI flag** — explicit per-invocation override. Highest
   priority because the user just typed it.
2. **Env var** — admin's debug / emergency-override channel.
   Survives restarts of the same shell.
3. **ConfigStore** (the user-config DB; opt-in via `--config-db`
   / `NORA_CONFIG_DB`) — what the user saved through the
   `/config` page. SQLite-backed, JSON-encoded values, keyed by
   `(module, key)`. Hydrates the cached `LLMConfigFile` /
   `RetrievalConfig` instances at startup via `apply_to_caches()`,
   so existing resolvers automatically pick up the layer.
4. **`config/*.json`** — project defaults checked into git.
   Structured by domain: `config/llm.json` (D-044) for LLM +
   embedding settings; `config/retrieval.json` (D-050) for
   retrieval knobs; `config/web.json` for the web server.
5. **Built-in defaults** — fallback constants in code
   (`_TYPE_*` dicts, `DEFAULT_*` constants). Project-checked-in
   values can be tested against these by leaving the JSON empty.

### Why this order

The most-specific, most-recent override wins. CLI flag = "I just
typed this." Env var = "this shell has it set." DB = "I saved
this earlier through the UI." JSON = "this is the project
default." Built-in = "this is what shipped."

Env vars sit **above** the DB so the admin keeps an emergency-
override path that can't be silently lost to a stale DB row.

### `/config` page

Renders the user-editable knobs grouped by module section
(LLM & Embedding, Retrieval & Grouping). Each section has three
sub-sections by category:

- **Features** — boolean toggles (`enable_grouping`,
  `skip_taxonomy`, etc.). Rendered as checkboxes.
- **Values** — model names, URLs, API keys (text or enum
  dropdowns; password input for `llm_api_key`).
- **Tunable parameters** — numeric scalars (`gap_threshold`,
  `max_distance_threshold`, `top_k_cap`) and per-QueryType maps
  (`bm25_weight_by_type` — table editor).

Saving:

1. Form-submitted values get coerced to typed Python values.
2. Each saved value is persisted as one DB row; per-QueryType
   maps are stored as a single JSON-encoded dict row.
3. The cache-overlay (`reapply_one`) is updated immediately.
4. `app.state.query_pipeline` is invalidated so the next query
   rebuilds with the new resolved values.

The Config page is opt-in: when `--config-db` is unset the page
renders **read-only** with a notice, and the resolver chain
falls through to the JSON files / built-in defaults as before.

### Per-QueryType table editor — `kind="dict_by_query_type"`

The schema field type added in commit 8efe110 generalizes to
any per-QueryType map:

```python
ConfigField(
    module="retrieval",
    key="bm25_weight_by_type",
    label="BM25 Weight by QueryType",
    kind="dict_by_query_type",
    value_kind="float",   # cell type — float / int / bool / string
    category="tunable",
    help="...",
)
```

The route iterates `QueryType` enum values to render one table
row per type; saving collects all `<module>__<key>__<query_type>`
form fields into one dict. Empty cells are skipped on save (the
resolver falls back to the built-in default for that type).

The remaining per-type maps (`top_k_by_type`,
`rerank_enabled_by_type`, `rewrite_enabled_by_type`,
`gap_threshold_by_type` per-type) follow the same pattern; their
migration from `pipeline.py` module-level dicts to `config/retrieval.json`
+ Config page is **Phase 4-migrate**, scheduled next.

### Verification — `[Query knobs]` log

Every query emits one structured log line at the resolver-chain
boundary:

```
[Query knobs] type=summarize top_k=50 (cap=none) bm25_weight=0.20 rerank=False rewrite=True threshold=0.7 grouping=False
```

Use this to confirm a Config-page edit took effect on the next
query.

## 15. Debugging retrieval quality

When retrieval feels "off" — answers look fabricated, relevant
reqs don't surface, or the not-found path fires on queries that
should have hit — work down this checklist before assuming the
algorithm is broken.

### 15.1 Most common cause: embedding-model mismatch

The vectorstore stores chunks embedded by the model named in
`<env_dir>/out/vectorstore/config.json`. The query path
re-embeds the user's query with whatever model the active
config resolves at runtime. If those two differ, every distance
is meaningless — vectors live in different spaces.

Verify with:

```bash
cat <env_dir>/out/vectorstore/config.json | grep -E "embedding_(provider|model)"
```

Compare against the model the query path will use: `config/llm.json`'s
`embedding_provider` / `embedding_model`, modulo CLI / env-var
overrides. The two must match. If they don't, either rebuild
the vectorstore against the new model, or update the query
config to match the existing vectorstore.

### 15.2 Confirm chunks carry the new metadata (D-046)

After D-046, every chunk carries `hierarchy_path` (a `list[str]`
with `plan_name` as the document root). Old vectorstores built
before D-046 won't have it; the context builder falls back to
the graph node, but retrieval-side grouping (Step 3 onwards)
won't see the document distinction in the embedding.

```bash
cd <repo_root> && python -c "
from core.src.vectorstore.store_chroma import ChromaDBStore
s = ChromaDBStore(persist_directory='<env_dir>/out/vectorstore')
r = s.get_all()
print(f'Total docs: {len(r.ids)}')
total = len(r.metadatas)
with_path = sum(1 for m in r.metadatas if m.get('hierarchy_path'))
print(f'With hierarchy_path: {with_path}/{total}')
for cid, m in list(zip(r.ids, r.metadatas))[:3]:
    print(f'  {cid} -> {m.get(\"hierarchy_path\")}')
"
```

Expect: `with_path == total`, and the first element of each
path should be the document root (e.g. `LTEDATARETRY`,
`LTE_OTA_Device_Management`). Empty paths or `None` mean the
vectorstore predates D-046 — rebuild required.

### 15.3 Threshold sweep — diagnose the relevance distribution

After D-047, the pipeline filters chunks by cosine distance. If
the threshold is wrong for the active model + corpus, either
relevant chunks get falsely dropped (no answers) or off-topic
chunks slip through (hallucinations). Save as
`/tmp/threshold_sweep.py` and run:

```python
"""Probe the relevance threshold against the live vectorstore."""
import sys
sys.path.insert(0, "<repo_root>")

from pathlib import Path

from core.src.query.pipeline import (
    QueryPipeline, load_graph, build_stub_graph_from_store, _NOT_FOUND_ANSWER,
)
from core.src.vectorstore import make_embedder
from core.src.vectorstore.config import VectorStoreConfig
from core.src.vectorstore.store_chroma import ChromaDBStore

VS_DIR = "<env_dir>/out/vectorstore"
GRAPH_PATH = Path("<env_dir>/out/graph/knowledge_graph.json")

cfg = VectorStoreConfig.load_json(Path(VS_DIR) / "config.json")
embedder = make_embedder(cfg)
store = ChromaDBStore(
    persist_directory=cfg.persist_directory,
    collection_name=cfg.collection_name,
    distance_metric=cfg.distance_metric,
)

if GRAPH_PATH.exists():
    graph = load_graph(GRAPH_PATH)
    bypass = False
else:
    graph = build_stub_graph_from_store(store)
    bypass = True

def run(query, threshold):
    p = QueryPipeline(
        graph, embedder, store, top_k=5,
        max_distance_threshold=threshold, enable_bm25=False,
    )
    if bypass:
        p._bypass_graph = True
    resp = p.query(query)
    not_found = resp.answer == _NOT_FOUND_ANSWER
    scores = [round(c.similarity_score, 4) for c in resp.retrieved_chunks]
    return resp.retrieved_count, not_found, scores

# Replace these with queries appropriate to your corpus —
# pick 2 in-domain queries you know should hit, and 2
# clearly out-of-domain queries you know should miss.
queries = [
    ("RELEVANT-1  : <in-domain query 1>", "<in-domain query 1>"),
    ("RELEVANT-2  : <in-domain query 2>", "<in-domain query 2>"),
    ("OFF-TOPIC-1 : Treaty of Westphalia", "Treaty of Westphalia"),
    ("OFF-TOPIC-2 : Recipe for chocolate cake", "Recipe for chocolate cake"),
]

print(f"Embedding: {cfg.embedding_provider} / {cfg.embedding_model}")
print(f"Distance:  {cfg.distance_metric}\n")

print("=== Baseline raw scores (threshold disabled) ===\n")
for label, q in queries:
    n, nf, scores = run(q, threshold=None)
    print(f"{label}\n  scores: {scores}\n")

print("=== Threshold sweep ===")
print(f"{'threshold':<12} {'query':<40} {'kept':>5} {'not_found':>10}")
for t in [0.8, 0.6, 0.5, 0.4, 0.3, 0.2]:
    for label, q in queries:
        n, nf, _ = run(q, threshold=t)
        print(f"{t:<12} {label:<40} {n:>5} {str(nf):>10}")
    print()
```

Run with: `python /tmp/threshold_sweep.py`

Read the baseline scores first:

- **Relevant queries should cluster low** (well under the
  threshold). On qwen3-embedding:4b-q8_0 + the OA corpus, in-
  domain top-5 distances were 0.20–0.41.
- **Off-topic queries should cluster high.** Same calibration:
  off-topic distances were 0.74–0.77.
- **The gap matters more than the absolute values.** A 0.30+
  gap between worst-relevant and best-off-topic means the
  threshold can sit comfortably in the middle. A narrow gap
  (< 0.15) means the embedding isn't separating in-domain from
  out-of-domain content well — reranker, BM25 weight, or
  embedding-model choice need attention before the threshold
  can do its job.

The default `max_distance_threshold = 0.5` is calibrated to
qwen3-embedding:4b-q8_0 on the OA corpus. Different models
will need different defaults. Override at runtime via:

```bash
NORA_MAX_DISTANCE_THRESHOLD=0.6 python -m core.src.web.app ...   # stricter / looser
NORA_MAX_DISTANCE_THRESHOLD=off python -m core.src.web.app ...   # disable
```

### 15.4 Run the full pipeline with explicit provider / model flags

When the underlying state (vectorstore, graph, taxonomy) is
suspect, rebuild end-to-end. The pipeline runner accepts CLI
flags for every provider knob; resolution priority is **CLI >
env var > config/llm.json > defaults**.

**Caveat — one-way flags.** `--skip-taxonomy` / `--skip-graph` /
`--rag-only` are `store_true`. They can force-skip a stage but
cannot un-skip one set in `config/llm.json`. To run the full
pipeline when `config/llm.json` has `skip_taxonomy: true` or
`skip_graph: true`, edit the file and flip those to `false`
first (or remove them). The CLI will not override an already-
true config value.

Full-pipeline command:

```bash
cd <repo_root> && python -m core.src.pipeline.run_cli \
  --env-dir <env_dir> \
  --start extract --end eval \
  --embedding-provider <ollama | sentence-transformers | huggingface> \
  --embedding-model <model-name> \
  --llm-provider <ollama | openai-compatible | mock> \
  --model <llm-model-name> \
  --model-timeout 600 \
  --standards-source <huggingface | 3gpp> \
  --verbose
```

#### Flag reference

| Flag | Purpose | Valid values |
|---|---|---|
| `--env-dir` | Per-env runtime dir (input/, out/, state/, ...) | absolute path |
| `--start` / `--end` | Stage range | `extract`, `profile`, `parse`, `resolve`, `taxonomy`, `standards`, `graph`, `vectorstore`, `eval` |
| `--embedding-provider` | Embedding backend | `sentence-transformers` / `huggingface` (alias) / `ollama` |
| `--embedding-model` | Embedding model | provider-specific (e.g. `all-MiniLM-L6-v2`, `qwen3-embedding:4b`, `qwen3-embedding:4b-q8_0`, `nomic-embed-text`) |
| `--llm-provider` | LLM backend | `ollama` / `openai-compatible` / `mock` |
| `--model` | LLM model name | e.g. `gemma3:12b`, `gemma4:e4b`, or for openai-compatible: `qwen/qwen3-235b-a22b`, etc. |
| `--model-timeout` | LLM request timeout (sec) | typically 300–600 for local Ollama on CPU |
| `--standards-source` | 3GPP spec source | `huggingface` (DOCX-only, no auth) / `3gpp` (FTP fallback) |
| `--verbose` | Per-stage logging | flag |
| `--continue-on-error` | Don't abort the pipeline on a single-stage failure | flag |
| `--skip-taxonomy` / `--skip-graph` / `--rag-only` | Force-skip stages (one-way; see caveat above) | flag |

#### Suggested provider combos

**A. Full local (no API key needed; slowest):**
```bash
--embedding-provider ollama --embedding-model qwen3-embedding:4b-q8_0 \
--llm-provider ollama --model gemma3:12b --model-timeout 600
```

**B. Local embeddings + remote LLM (best taxonomy quality):**
```bash
--embedding-provider ollama --embedding-model qwen3-embedding:4b-q8_0 \
--llm-provider openai-compatible --model qwen/qwen3-235b-a22b --model-timeout 600
# also: NORA_LLM_BASE_URL=https://openrouter.ai/api/v1 NORA_LLM_API_KEY=sk-...
```

**C. Fast local (smaller embedding + smaller LLM):**
```bash
--embedding-provider sentence-transformers --embedding-model all-MiniLM-L6-v2 \
--llm-provider ollama --model gemma4:e4b --model-timeout 300
```

### 15.5 Targeted vectorstore rebuild only

If only the vectorstore is suspect (taxonomy / graph already
look fine), rebuild just that stage:

```bash
cd <repo_root> && python -m core.src.vectorstore.vectorstore_cli \
  --trees-dir <env_dir>/out/parse \
  --persist-dir <env_dir>/out/vectorstore \
  --provider <ollama | sentence-transformers> \
  --model <embedding-model-name> \
  --rebuild
```

Notes:
- The trees source is `<env_dir>/out/parse/` (parsed `*_tree.json`
  files), **not** `<env_dir>/out/resolve/` (cross-reference
  outputs only).
- `--taxonomy` is optional; omit it for RAG-only setups where
  the taxonomy stage has been skipped.
- The CLI saves the resolved config to
  `<env_dir>/out/vectorstore/config.json`. Downstream query
  paths read that file to construct the embedder, so rebuilding
  propagates the model choice automatically.

### 15.6 Truncation warnings during rebuild

```
WARNING Text N length 9415 > max_input_chars 8000; truncating
        (1415 chars dropped)
```

Intentional safety cap. Ollama embedding models reject very
long inputs (qwen3-embedding fails above ~16K chars; the 8K
default is conservative). The first 8K of a chunk carries
header lines + title + opening text — the load-bearing
content for retrieval. Trailing tables / image surrounding
text get truncated, a small bounded loss.

To raise the cap if you know your model handles more, set
`extra={"ollama_max_input_chars": 12000}` on `VectorStoreConfig`.

### 15.7 Common failure modes

| Symptom | Likely cause | Diagnostic |
|---|---|---|
| Every query returns "not found" | Embedding model mismatch (built with X, queried with Y) | §15.1 — compare `<env_dir>/out/vectorstore/config.json` against the active config |
| Relevant queries return "not found"; off-topic returns answers | Threshold too strict for current model | §15.3 — sweep; raise threshold or disable |
| Off-topic queries return synthesized answers | Threshold too loose, or filter disabled | §15.3 — confirm threshold value in pipeline-build log |
| Vectorstore rebuild shows `Loaded 0 parsed trees` | Wrong `--trees-dir` (pointed at `out/resolve` instead of `out/parse`) | §15.5 |
| `Loaded 0 parsed trees` and trees-dir is correct | Parse stage hasn't run; rerun the pipeline up to parse | `--start extract --end parse` |
| Acronym queries get hallucinated answers | Glossary chunks missing from vectorstore (rebuilt without `definitions_map` populated) | Spot-check with §15.2; ensure `<doc_type>=glossary_entry` chunks exist |
| Hierarchy paths show single-element `[doc_root]` only | Requirements have no hierarchy populated by parser | Open a parsed tree JSON, inspect `requirements[*].hierarchy_path` |

## 16. ADR cross-reference

- **D-001** — Graph routes, RAG ranks (foundational).
- **D-032** — Per-document `definitions_map` + chunk-build inline
  expansion. (See §8.)
- **D-038** — Table-anchored definitions extraction (extends D-032
  for table-format glossaries).
- **D-039** — Entity-priority graph scoping. (See §2.)
- **D-040** — Type-aware top\_k + cross-doc list-style detection.
  (See §4.4.)
- **D-041** — BM25 hybrid retrieval (sparse + dense, RRF,
  per-type weights). (See §4.)
- **D-042** — Parent-chunk subsection augmentation (opt-in,
  default off — kept available for corpora with rich-bodied
  parents).
- **D-043** — Acronym lookup chain (parser fix + glossary chunks
  + query-side pin). Adds glossary-aware retrieval as a
  deterministic answer surface for short definitional queries.
  (See §6.)
- **D-046** — Document-rooted hierarchy paths in chunk text +
  metadata. Embedding captures Document > Section > Subsection.
  Input that Stage 4.7 grouping (§11) reads. (See §1's
  "Contract" list.)
- **D-047** — Relevance threshold + "not found" response (Stage
  4.5). Off-topic queries return a deterministic message
  instead of LLM hallucination from weak fragments. (See §10.)
- **D-049** — Stage 4.7 hierarchy grouping with user-facing
  disambiguation. "The system shall not pretend it is an
  Oracle." Auto-commit when groups separate cleanly; surface a
  disambiguation response when they don't. (See §11.)
- **D-050** — Phase 3-config infrastructure: `config/retrieval.json`
  + 3-tier resolver chain extension. Pattern for Phase 4-migrate
  (rest of the per-type maps). (See §14.)
- **D-051** — FACT and SUMMARIZE intent classification.
  Phrasing-driven routing on top of the existing scope-shape
  types; per-intent knob bundles. (See §12.)
- **D-052** — Stage 6.5 citation audit. Per-sentence regex check
  for inline citations; flags fabricated req IDs. (See §13.)
- **D-053** — Config-page DB layer in resolver chain (CLI > env
  > **DB** > JSON > defaults). User-edited overrides via the
  `/config` page; SQLite-backed; opt-in via `--config-db`.
  (See §14.)
