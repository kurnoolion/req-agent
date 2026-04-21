# Knowledge Graph in NORA — What the Code Actually Does

This document describes how the Knowledge Graph (KG) is used **in the current
implementation**, walked from the code. It is a narrower document than the
TDD: the TDD (`TDD_Telecom_Requirements_AI_System.md`) is the full design;
this document tracks what is actually built and where the implementation
diverges from the design. Line references point at the real code.

---

## 1. Where the KG Lives

Two packages carry the graph:

- `src/graph/` — the schema and the builder that constructs the graph from
  pipeline outputs.
- `src/query/` — the six-stage query pipeline that uses the graph.

The graph itself is a `networkx.DiGraph` (`src/graph/builder.py:73`). There
is no Neo4j, no persistent query engine — it is an in-memory DiGraph
serialized to JSON/GraphML.

Serialization:

- `KnowledgeGraphBuilder.save_json` writes node-link JSON via
  `nx.node_link_data` (`src/graph/builder.py:659`).
- `load_graph(path)` in `src/query/pipeline.py:141` re-loads it at query time.

So the runtime flow is: builder runs once per ingestion → graph JSON on disk
→ query pipeline loads the JSON into a DiGraph and keeps it in memory for
the life of the process.

---

## 2. What Is Actually in the Graph

### 2.1 Node types — implemented (`src/graph/schema.py:21`)

```
MNO, Release, Plan, Requirement, Standard_Section, Feature
```

**Not implemented: Test_Plan and Test_Case.** The module docstring says
so explicitly at `src/graph/schema.py:6`:

> Node types implemented (skipping Test_Plan / Test_Case — Step 4 deferred)

This has downstream consequences for the query pipeline (see §6).

### 2.2 Edge types — implemented (`src/graph/schema.py:33`)

```
Organizational:   has_release, contains_plan
Within-doc:       parent_of, belongs_to
Cross-document:   depends_on, shared_standard
Standards:        references_standard, parent_section
Feature:          maps_to, feature_depends_on
```

**Divergences from the TDD design:**

| Design (TDD §6.2) | Implementation | Status |
|-------------------|----------------|--------|
| `defers_to` / `constrains` / `overrides` / `extends` with `delta_summary` | Single untyped `references_standard` edge | **Flattened.** The typed semantics and pre-computed deltas are not built. |
| `tested_by` / `tests` / `test_plan_for` | — | **Deferred.** Test case nodes don't exist. |
| `version_of` (Requirement → Requirement across releases) with `change_type` | — | **Deferred.** No cross-release edges. |
| `succeeds` (Release → Release) | — | **Deferred.** |
| `concept_link` (LLM-tagged) | — | **Deferred.** |

### 2.3 Node ID conventions (`src/graph/schema.py:66-93`)

IDs are deterministic strings:

```
MNO:          mno:VZW
Release:      release:VZW:2026_feb
Plan:         plan:VZW:2026_feb:LTEDATARETRY
Requirement:  req:VZ_REQ_LTEDATARETRY_7748         ← req_id alone, globally unique
Std Section:  std:24.301:11:5.5.1.2.5
Feature:      feature:IMS_REGISTRATION
```

The requirement ID scheme matters: the vector store's `chunk_id` is
`req:<req_id>` (`src/vectorstore/chunk_builder.py:107`), **identical to the
graph node ID**. This is how the query pipeline joins chunks back to graph
nodes (`src/query/rag_retriever.py:208`:
`graph_node_id=chunk_id`).

---

## 3. Graph Storage and Runtime — NetworkX In-Memory DiGraph

**There is no external graph database.** The "graph DB" in NORA is
NetworkX, a pure-Python in-memory library. No Neo4j, no ArangoDB, no
JanusGraph, no remote query engine. `requirements.txt` declares
`networkx>=3.0` as the only graph dependency.

This is a deliberate PoC choice. The TDD (§5.8) calls out Neo4j as a
production candidate, but production migration is not scheduled.

### 3.1 Data structure

The graph is a single `networkx.DiGraph` instance, created in the
builder's constructor (`src/graph/builder.py:73`):

```python
self.graph = nx.DiGraph()
```

Internally this is two Python dicts — one for nodes (keyed by node ID
string), one for adjacency (keyed by source ID → dict of target ID →
edge attributes). Both node and edge attributes are stored inline as
Python dicts; there is no schema enforcement at the storage layer.
The enums in `src/graph/schema.py` (`NodeType`, `EdgeType`) are used
only as string constants when populating the `node_type` / `edge_type`
attributes.

### 3.2 Persistence

The graph is persisted **once per pipeline run**, at the end of
pipeline stage 7 (`run_graph` in `src/pipeline/stages.py:395-417`):

```python
graph_path = out_dir / "knowledge_graph.json"
with open(graph_path, "w") as f:
    json.dump(nx.node_link_data(graph), f, indent=2)
```

The file lives at `<doc_root>/output/graph/knowledge_graph.json` (the
pipeline's stage-output convention). A matching `graph_stats.json`
records node/edge counts by type.

`nx.node_link_data` produces a JSON with two arrays: `nodes` (each with
`id` + attributes) and `links` (each with `source`, `target`, +
attributes). This is NetworkX's canonical lossless JSON form.

A second serializer exists for tooling interop:
`KnowledgeGraphBuilder.save_graphml` (`src/graph/builder.py:643`)
writes GraphML via `nx.write_graphml`. Because GraphML cannot hold
list or dict attributes, the method first JSON-stringifies any
non-scalar attributes in a copy of the graph. This is used for
opening the graph in desktop tools (Gephi, yEd), not by the runtime.

### 3.3 Load path at query time

`load_graph(path)` in `src/query/pipeline.py:141`:

```python
with open(graph_path) as f:
    data = json.load(f)
graph = nx.node_link_graph(data)
```

The returned DiGraph is passed by reference into every query-time
consumer (`MNOReleaseResolver`, `GraphScoper`, `ContextBuilder`). It
is **not re-loaded per query** — it stays in memory for the life of
the process. The web frontend (`src/web/`) loads it once at app
startup; a CLI query loads it once per invocation.

### 3.4 How the graph is queried at runtime

Every query-time operation uses the **plain NetworkX Python API**.
There is no query language (no Cypher, no Gremlin), no indexes
beyond the built-in ID → node dict, and no transaction model.

Concrete operations actually used, with file references:

| Operation | NetworkX call | Where |
|-----------|---------------|-------|
| Node existence / lookup by ID | `nid in graph`, `graph.nodes[nid]` | `graph_scope.py:165`, `context_builder.py:171`, etc. |
| Scan all nodes | `graph.nodes(data=True)` | `resolver.py:89`, `graph_scope.py:226, 260`, `graph_cli.py:114, 122` |
| Scan all edges | `graph.edges(data=True)` | `graph_cli.py:138, 156, 166` |
| Outgoing edges of a node | `graph.out_edges(nid, data=True)` | `graph_scope.py:305`, `context_builder.py:210, 235` |
| Incoming edges of a node | `graph.in_edges(nid, data=True)` | `graph_scope.py:332`, `context_builder.py:196`, `graph_cli.py:126` |
| Predecessors | `graph.predecessors(nid)` | `graph_scope.py:193` |
| Edge existence check | `graph.has_edge(u, v)` | `builder.py:302, 590` |
| Undirected view | `graph.to_undirected()` | `graph_cli.py:182` (connectivity audit) |
| Connected components | `nx.connected_components(undirected)` | `graph_cli.py:183` |
| Weakly-connected count | `nx.number_weakly_connected_components(graph)` | `stages.py:423` |
| Shortest path | `nx.shortest_path(undirected, u, v)` | `graph_cli.py:201` (diagnostic only, not in query path) |

**Filtering queries are full scans.** `_plan_lookup` in
`graph_scope.py:226` iterates every node in the graph to find
requirements in a given plan; there is no secondary index on
`plan_id`. `_title_search` (line 260) similarly does a linear scan
with substring matching. This is acceptable at PoC scale (thousands
of nodes, not millions) but is the first thing that would change if
the graph moved to a real graph DB.

**Traversal is a hand-written BFS.** `GraphScoper._traverse`
(`graph_scope.py:287`) implements depth-limited BFS directly, with:

- a `frontier` set advanced depth-by-depth,
- a `visited` set to avoid cycles,
- allowed-edge filtering per query type,
- scope re-check on every visited Requirement node,
- a geometric score decay (`0.7 ** (depth + 1)`).

There is no reliance on any NetworkX traversal function —
`nx.bfs_edges` / `nx.descendants` are not used. The reason is that
the traversal needs per-edge-type filtering and per-node scope
checks that are easier to express inline.

### 3.5 Operational consequences

- **Single-process.** Shared state across processes would need an
  external DB; none exists.
- **Full load before first query.** Bigger graphs ⇒ slower cold
  start, larger memory footprint.
- **No concurrent writes during query.** Queries are read-only; the
  builder rewrites the JSON only as part of a pipeline run.
- **Atomic rebuild.** A rebuild produces a new `knowledge_graph.json`;
  processes already running continue to use the version they loaded.
- **Move to Neo4j is scoped but not started.** The schema (`NodeType`,
  `EdgeType`, ID conventions) is already expressed in a way that maps
  cleanly to Cypher labels and relationship types, so the migration
  would mostly be a swap of the access layer; the query pipeline's
  six stages would remain.

---

## 4. How the Graph Is Built

Entry point: `KnowledgeGraphBuilder.build(trees_dir, manifests_dir,
taxonomy_path, standards_dir)` at `src/graph/builder.py:77`.

Inputs (all produced by earlier pipeline stages):

- `*_tree.json` from the parser (`trees_dir`)
- `*_xrefs.json` from the resolver (`manifests_dir`)
- `taxonomy.json` from the taxonomy stage
- `TS_*/Rel-*/sections.json` + `reference_index.json` from the standards
  stage

Execution order (`src/graph/builder.py:99-112`):

```
1. _build_requirement_graph(trees)      # MNO, Release, Plan, Requirement + parent_of
2. _build_xref_edges(manifests)         # depends_on
3. _build_standards_graph(refs, …)      # Standard_Section + references_standard + parent_section
4. _build_feature_graph(taxonomy, …)    # Feature + maps_to + feature_depends_on
5. _build_shared_standard_edges()       # shared_standard
```

### 4.1 Requirement graph (`_build_requirement_graph`, line 180)

For each parsed tree:

- Add MNO node once (`mnos_seen` dedup).
- Add Release node once; edge `MNO --has_release--> Release`.
- Add Plan node; edge `Release --contains_plan--> Plan`.
- For each requirement:
  - Add Requirement node. Stored attributes include `req_id`, `plan_id`,
    `mno`, `release`, `section_number`, `title`, `text`, `zone_type`,
    `hierarchy_path` (line 239-251). These are exactly the attributes the
    query pipeline later reads.
  - Edge `Requirement --belongs_to--> Plan`.
  - If `parent_req_id` exists *and* that parent is in the same tree, edge
    `Parent --parent_of--> Child` (line 259-273). Parents outside the tree
    are silently skipped, which means `parent_of` is strictly
    within-document.

### 4.2 Cross-reference edges (`_build_xref_edges`, line 288)

Two kinds of `depends_on` edges, both from resolved cross-references only
(`ref.status == "resolved"`):

- **Internal refs** (same plan): `req --depends_on--> req`, with
  `ref_type="internal"`. A guard prevents duplicating an existing
  `parent_of` edge as `depends_on` (line 302).
- **Cross-plan refs**: here the implementation **does not link req → req**.
  Instead it links `req --depends_on--> Plan` (line 318-331) with
  `ref_type="cross_plan"`. The inline comment explains: creating edges to
  every requirement in the target plan would be noisy.

This is a meaningful divergence from the TDD's example
(`VZ_REQ_LTEDATARETRY_41013 --depends_on--> VZ_REQ_LTESMS_XXXX`): the real
edge lands on the *plan*, not a specific requirement. Downstream traversal
then relies on graph scope + RAG to narrow down which requirement in that
plan is actually relevant.

### 4.3 Standards graph (`_build_standards_graph`, line 341)

Two passes:

1. For each extracted sections file:
   - Create a spec-level node `std:<spec>:<release_num>` (section="").
   - For each referenced section, create `std:<spec>:<rel>:<section>` with
     `title`, `text`, `depth` attributes.
   - Edge `spec_node --parent_section--> section_node`.
   - Also create nodes for "context sections" (siblings / definitions used
     for context).

2. For each resolved standards reference in the xref manifests, add
   `Requirement --references_standard--> Standard_Section`, with
   `release` and `release_source` on the edge (line 443-448).

The edge is **always `references_standard`** — there is no runtime
classification into `defers_to` / `constrains` / `overrides` / `extends`,
and no `delta_summary` is computed. This simplification is material: the
TDD's "standards comparison" capability is stubbed at this layer.

Each time a `references_standard` edge is added, the builder records the
`(std_node → [req_node…])` reverse index in `self._std_ref_index`
(line 452) for the next step.

### 4.4 Feature graph (`_build_feature_graph`, line 485)

Two passes. Pass 1 creates all Feature nodes. Pass 2 creates `maps_to`
edges with a deliberately **coarse** rule (line 532-556):

- For every plan listed in `feat.is_primary_in`, ALL requirements in that
  plan get `Req --maps_to--> Feature` with `mapping_type="primary"`.
- Same for `is_referenced_in`, with `mapping_type="referenced"`.

An inline comment calls this out:

> A feature is primary in certain plans — all reqs in those plans map to
> this feature. This is a coarse mapping that a real LLM would refine to
> specific requirement subsets.

So a query that lands on a feature gets *every* requirement in every
primary/referenced plan, not a curated subset. The narrowing happens later
at the RAG ranking step.

`feature_depends_on` edges come from `feat.depends_on_features`.

### 4.5 Shared-standard edges (`_build_shared_standard_edges`, line 576)

Uses the `_std_ref_index` built in §3.3. For every standard node with ≥2
referring requirements, it creates a `shared_standard` edge between each
pair — but **only if the two requirements are in different plans** (line
589). Same-plan pairs are skipped, on the assumption they are already
connected by `parent_of` or `depends_on`.

Edges are added in one direction only (`if not has_edge(r1, r2)`), even
though the semantic is undirected. The traversal code handles this: see §6.3.

---

## 5. Feature Taxonomy — How It Plugs Into the KG

The feature taxonomy is a separate artefact produced by pipeline stage 5
(`taxonomy`) and consumed by three places: the graph builder, the vector
chunk builder, and the query-time GraphScoper. It is the glue that makes
cross-document and cross-MNO navigation possible, because individual
requirement documents do not declare which capabilities they belong to —
the taxonomy assigns that membership.

### 5.1 Data model (`src/taxonomy/schema.py`)

The LLM extractor emits per-document `DocumentFeatures`
(`src/taxonomy/schema.py:26`):

- `primary_features: list[Feature]` — features the document defines
- `referenced_features: list[Feature]` — features the document mentions
  but are defined elsewhere
- `key_concepts: list[str]` — specific protocols, timers, cause codes,
  procedures called out in the headings

The consolidator merges these into `TaxonomyFeature` entries
(`src/taxonomy/schema.py:60`). One per unique `feature_id`, carrying:

- `name`, `description`, `keywords`
- `is_primary_in: list[plan_id]` — plans where this feature is a main topic
- `is_referenced_in: list[plan_id]` — plans that touch it
- `source_plans: list[plan_id]` — union of the two above
- `mno_coverage: dict[mno, list[plan_id]]` — which plan(s) of which MNO(s)
  contribute
- `depends_on_features: list[feature_id]` — inter-feature dependencies

The final output is a `FeatureTaxonomy` (`src/taxonomy/schema.py:74`)
serialized to `<doc_root>/output/taxonomy/taxonomy.json`.

### 5.2 How it is built

Two stages in `src/taxonomy/`:

- **`extractor.py`.** An LLM call per document. Input is the plan
  metadata plus the section-heading table of contents from the parser
  (`src/taxonomy/extractor.py:18-78`). The prompt asks the model to
  return `primary_features`, `referenced_features`, and `key_concepts`
  as JSON. Each feature gets a `confidence` score from the model.

- **`consolidator.py`.** Pure Python merge across all documents
  (`TaxonomyConsolidator.consolidate`, line 29). Deduplicates by
  `feature_id`, accumulates `is_primary_in` / `is_referenced_in` /
  `source_plans` / `mno_coverage`, unions the `keywords` lists.

**Gap.** The consolidator's docstring calls out explicitly
(`src/taxonomy/consolidator.py:7-8`):

> Cross-MNO consolidation (TDD Step 2 full) uses the LLM to align
> features across MNOs. That's deferred until we have multi-MNO data.

So the current consolidator is a *structural* merge keyed on
`feature_id` only. If VZW's extractor names a feature `DATA_RETRY`
and TMO's extractor names the same capability `RETRY_PROCEDURES`,
they will sit as two separate `TaxonomyFeature` entries and *not*
share a Feature node in the graph. The LLM-driven semantic alignment
that the TDD calls for is not wired.

### 5.3 Taxonomy → Graph (how the builder reads it)

`KnowledgeGraphBuilder._build_feature_graph`
(`src/graph/builder.py:485`) is the only place the graph consumes the
taxonomy.

**Pass 1 — Feature nodes** (line 509-522). One node per
`TaxonomyFeature`, ID `feature:<feature_id>`. Node attributes stored
verbatim from the taxonomy:

```
feature_id, name, description, keywords, mno_coverage, source_plans
```

Note what is **not** stored on the node: `is_primary_in` and
`is_referenced_in` (they are used only during edge construction),
and `depends_on_features` (used for `feature_depends_on` edges).

**Pass 2 — `maps_to` edges** (line 532-556). The coarse mapping
already called out in §4.4 above:

```python
for p in feat.is_primary_in:
    for rid in plan_reqs.get(p, []):          # EVERY req in that plan
        graph.add_edge(req_node, feat_node,
                       edge_type="maps_to",
                       mapping_type="primary")
for p in feat.is_referenced_in:
    for rid in plan_reqs.get(p, []):          # EVERY req in that plan
        graph.add_edge(..., mapping_type="referenced")
```

An edge's `mapping_type` attribute distinguishes "primary" from
"referenced", but no query code currently branches on it.

**Pass 3 — `feature_depends_on` edges** (line 559-566). Feature-to-feature
directed edges from the taxonomy's `depends_on_features` list.

### 5.4 Taxonomy → Vector store (chunk metadata)

`ChunkBuilder._build_plan_feature_map`
(`src/vectorstore/chunk_builder.py:232`) inverts the taxonomy into a
`{plan_id: [feature_id, …]}` table. A plan lands in the table once per
feature where it appears in either `is_primary_in` or `is_referenced_in`.

Every chunk's metadata then carries that plan's feature list
(`src/vectorstore/chunk_builder.py:104`):

```python
metadata = {
    "mno": mno,
    "release": release,
    "doc_type": "requirement",
    "plan_id": plan_id,
    "req_id": req_id,
    "section_number": …,
    "zone_type": …,
    "feature_ids": feature_ids,    # ← from taxonomy
}
```

**But the retriever does not currently filter on `feature_ids`.**
Grepping `src/query/rag_retriever.py` for `feature_ids` or `feature`
returns nothing. The retriever filters by `req_id` (when graph scoping
produced candidates) or by `mno`+`release` (fallback). The
`feature_ids` metadata is stored for future use — for example, a
taxonomy-only retrieval mode that bypasses graph scoping. It is
currently dead weight on every chunk.

### 5.5 Taxonomy → Query time

The taxonomy influences query time through two codepaths:

**Analyzer — `likely_features` extraction.** `MockQueryAnalyzer` uses a
hard-coded keyword table, `_FEATURE_KEYWORDS` at
`src/query/analyzer.py:60`:

```python
_FEATURE_KEYWORDS = {
    "DATA_RETRY":         ["data retry", "retry", "throttle", …],
    "SMS":                ["sms", "short message", …],
    "IMS_REGISTRATION":   ["ims", "volte", "sip", …],
    "TIMER_MANAGEMENT":   ["timer", "t3402", "t3411", …],
    …
}
```

When the user query contains any of these surface forms, the matching
feature IDs are emitted as `intent.likely_features`.

**This table is NOT loaded from `taxonomy.json`.** It is a literal dict
in the analyzer module. Two consequences:

1. Adding a new feature to the taxonomy (or re-running the LLM
   extractor with different IDs) does *not* make it searchable via
   the mock analyzer unless the `_FEATURE_KEYWORDS` dict is edited by
   hand.
2. If the LLM-extractor picks a `feature_id` string that isn't in
   `_FEATURE_KEYWORDS`, the analyzer will never emit it in
   `likely_features`, the scoper will never find a matching
   `feature:<id>` node, and that whole branch of the graph is dark to
   the mock query path. (The real LLMQueryAnalyzer does not have this
   coupling, but it is not the default.)

**Scoper — feature-driven seed expansion.** `GraphScoper._feature_lookup`
(`src/query/graph_scope.py:180`) is where taxonomy-derived edges pay
off:

```python
for fid in intent.likely_features:
    fnid = f"feature:{fid}"
    if fnid not in self._graph:
        continue
    for pred in self._graph.predecessors(fnid):           # ← maps_to⁻¹
        edge_data = self._graph.edges[pred, fnid]
        if edge_data.get("edge_type") != "maps_to":
            continue
        # … scope-filter, add as seed Requirement node
```

Every requirement in `is_primary_in` or `is_referenced_in` plans —
filtered to the resolved MNO/release — becomes a seed. The scoper then
expands one or two hops along edges appropriate to the query type
(§6.3 of this doc). The taxonomy is what lets a query about "IMS
registration" find VZW *and* TMO requirements in one call: both point
at the same `feature:IMS_REGISTRATION` node (assuming cross-MNO
alignment was done, which today it is not — see §5.2).

### 5.6 Concrete example of taxonomy carrying a query

Query: *"What VZW requirements cover backoff timers during data retry?"*

Assume the taxonomy contains:

```json
{
  "feature_id": "DATA_RETRY",
  "is_primary_in": ["LTEDATARETRY"],
  "is_referenced_in": ["LTESMS"]
},
{
  "feature_id": "TIMER_MANAGEMENT",
  "is_primary_in": ["LTEDATARETRY"],
  "is_referenced_in": ["LTEAT", "LTESMS"]
}
```

Analyzer:

- "data retry" → `DATA_RETRY`
- "backoff" → `DATA_RETRY` (also matches that keyword list)
- "timer" → `TIMER_MANAGEMENT`
- `likely_features = ["DATA_RETRY", "TIMER_MANAGEMENT"]`

GraphScoper feature lookup:

- `feature:DATA_RETRY` → predecessors along `maps_to`:
  all reqs in LTEDATARETRY (primary) ∪ all reqs in LTESMS (referenced)
- `feature:TIMER_MANAGEMENT` → predecessors along `maps_to`:
  all reqs in LTEDATARETRY (primary) ∪ all reqs in LTEAT (referenced)
  ∪ all reqs in LTESMS (referenced)
- Union, scope-filtered to VZW/2026_feb.

The seed set is **every requirement in four plans** of VZW's Feb 2026
release. This is the granularity problem: "backoff timers during data
retry" reaches hundreds of requirements before RAG ranking. The
coarse-mapping choice in §5.3 is what forces this.

Traversal then follows `depends_on` / `parent_of` /
`references_standard` one hop (SINGLE_DOC or FEATURE_LEVEL depth),
RAG ranks by vector similarity, context builder enriches each
surviving chunk with hierarchy path, parent text, standards text, and
depends-on annotations.

### 5.7 Gaps summary (taxonomy ↔ KG)

| Concern | Current state |
|---------|---------------|
| Cross-MNO feature alignment | Structural merge by `feature_id` only. Two MNOs with different IDs for the same capability → two separate Feature nodes. Explicitly deferred in `consolidator.py:7-8`. |
| Analyzer keyword source | Hard-coded dict (`analyzer.py:60`), not loaded from `taxonomy.json`. Taxonomy IDs and analyzer keys can drift. |
| `maps_to` granularity | Plan-level (every req in an `is_primary_in` or `is_referenced_in` plan). A surgical LLM-driven req-to-feature assignment is the documented TODO. |
| `feature_ids` chunk metadata | Populated on every chunk. Never used as a filter by the retriever today. Available for a future "features-only" retrieval mode. |
| `mapping_type` on edges | Stored (`"primary"` vs `"referenced"`) but no query code branches on it. |
| `feature_depends_on` traversal | Edges are built but no `_TRAVERSAL_EDGES` entry references them. Walking feature→feature dependencies is not part of any current query type. |

---

## 6. The Six-Stage Query Pipeline

Orchestrated by `QueryPipeline.query()` at `src/query/pipeline.py:77`.

```
query_text
    │
    ▼
Stage 1: MockQueryAnalyzer.analyze()         src/query/analyzer.py
    │  → QueryIntent {entities, concepts, mnos, releases, query_type,
    │                 doc_type_scope, standards_refs, likely_features,
    │                 plan_ids}
    ▼
Stage 2: MNOReleaseResolver.resolve()        src/query/resolver.py
    │  → ScopedQuery {intent, scoped_mnos: [MNOScope(mno, release)]}
    ▼
Stage 3: GraphScoper.scope()                 src/query/graph_scope.py
    │  → CandidateSet {requirement_nodes, standards_nodes, feature_nodes}
    ▼
Stage 4: RAGRetriever.retrieve()             src/query/rag_retriever.py
    │  → list[RetrievedChunk]
    ▼
Stage 5: ContextBuilder.build()              src/query/context_builder.py
    │  → AssembledContext {system_prompt, context_text, chunks}
    ▼
Stage 6: MockSynthesizer.synthesize()        src/query/synthesizer.py
    → QueryResponse {answer, citations, …}
```

A `_bypass_graph` flag on the pipeline (`src/query/pipeline.py:75`) lets
Stage 3 be skipped entirely, yielding a pure-RAG baseline for comparison.

### 6.1 Stage 1 — MockQueryAnalyzer (`src/query/analyzer.py`)

Keyword-based, no LLM. It extracts:

- **MNOs** via alias table (`_MNO_ALIASES` at line 28: verizon/vzw/vz →
  VZW, etc.)
- **Plans** via `_PLAN_ALIASES` (line 41: "data retry" → LTEDATARETRY,
  "sms" → LTESMS, …)
- **Features** via `_FEATURE_KEYWORDS` (line 60: each feature ID has a list
  of surface forms — e.g., TIMER_MANAGEMENT matches "t3402", "t3411",
  "backoff timer").
- **Standards** via regex on `3GPP TS X.Y`
- **Requirement IDs** via regex `VZ_REQ_\w+_\d+`
- **Releases** via month+year / year+month / "latest" patterns.
- **Query type** — implemented, but classification quality is bounded by
  keywords. The defaults used for traversal (§6.3) are accepting of
  misclassification.

An `LLMQueryAnalyzer` class is present but not the default
(`src/query/pipeline.py:67`: `analyzer=analyzer or MockQueryAnalyzer()`).

### 6.2 Stage 2 — MNOReleaseResolver (`src/query/resolver.py`)

This stage **uses the graph directly** as a metadata source.

At construction, `_discover_available` (line 82) walks all Release nodes
and builds `{mno: [releases sorted reverse-lex]}`. Reverse string sort is
"latest-first" under the `YYYY_MMM` convention.

Then `resolve(intent)` (line 34):

- If user named an MNO, check it against `_available` (drop unknown MNOs
  with a warning).
- If user named a release, try exact / substring / token match
  (`_match_release` at line 104). Fall back to latest if no match.
- If user named no MNO, fan out to ALL known MNOs at their latest release.

The output is a list of `MNOScope(mno, release)` pairs. Every downstream
stage uses this list.

**Gap vs TDD:** no `is_latest` flag on Release nodes; "latest" is computed
by reverse string sort of whatever Release nodes are in the graph.

### 6.3 Stage 3 — GraphScoper (`src/query/graph_scope.py`)

This is where the graph earns its keep. Flow in `scope()` (line 87):

1. **Entity lookup** (`_entity_lookup`, line 156): for each entity, try
   `req:<entity>` as a node ID directly. Only exact `req:...` matches hit
   — entity names like "T3402" will not match here because the graph
   doesn't index timer names, only req IDs.

2. **Feature lookup** (`_feature_lookup`, line 180): for each
   `likely_features` from the analyzer, walk predecessors of the
   `feature:<id>` node along `maps_to` edges. Only Requirement nodes in
   scope are kept.

3. **Plan lookup** (`_plan_lookup`, line 219): if the analyzer extracted
   `plan_ids` but the above found no seeds, take *all* requirements in
   those plans (scope-filtered).

4. **Title search fallback** (`_title_search`, line 249): if still nothing,
   scan every Requirement node's `title` and `text` for any
   concept/entity term. Scoring is `0.3 + 0.2 * min(matches, 3)`.

5. **Edge traversal** (`_traverse`, line 287): from all seed nodes, expand
   along edges typed by the query type, for `max_depth` hops. The edge
   set per query type is fixed in `_TRAVERSAL_EDGES` (line 45):

   ```
   SINGLE_DOC:              depends_on, parent_of, references_standard
   CROSS_DOC:               + shared_standard
   CROSS_MNO_COMPARISON:    maps_to, references_standard
   FEATURE_LEVEL:           maps_to, depends_on, references_standard
   STANDARDS_COMPARISON:    references_standard, parent_section
   GENERAL:                 depends_on, parent_of, references_standard,
                            shared_standard, maps_to
   ```

   **Note:** `QueryType.RELEASE_DIFF` and `QueryType.TRACEABILITY` exist in
   the enum (`src/query/schema.py:20`) but **have no entry** in
   `_TRAVERSAL_EDGES`. They fall through to `GENERAL` via
   `.get(qt, _TRAVERSAL_EDGES[QueryType.GENERAL])` (line 100). Release
   diff and traceability are effectively unsupported as first-class
   query types today.

   Traversal walks BOTH `out_edges` and `in_edges` (line 305 and 332). This
   matters for `maps_to` (stored Req→Feature — so feature lookup needs
   predecessors) and for `shared_standard` (stored in one direction).
   Score decays geometrically: `0.7 ** (depth + 1)`.

   Every crossed Requirement node gets re-checked against scope
   (line 316-318 and 342-344), so expansion cannot escape the MNO/release
   frame.

The returned `CandidateSet` partitions nodes by type into
`requirement_nodes`, `standards_nodes`, `feature_nodes`. Only
requirements and standards end up in the prompt context; features are
useful mainly as hubs during traversal.

### 6.4 Stage 4 — RAGRetriever (`src/query/rag_retriever.py`)

The retriever combines graph candidates with the vector store.

`retrieve()` (line 44) has two modes:

- **Scoped retrieval** (`_scoped_retrieve`, line 97). Used when graph
  scoping produced ≥1 requirement node. Embeds the query, then queries
  ChromaDB with `where={"req_id": {"$in": [candidate_req_ids]}}` — the
  graph candidate set acts as a hard metadata filter. If the list exceeds
  500 ids (ChromaDB `$in` constraint), it queries unfiltered and filters
  client-side.

- **Metadata retrieval** (`_metadata_retrieve`, line 129). Used when
  graph scoping returned zero requirement nodes. Falls back to a pure
  metadata filter on `mno`+`release` from the MNO scopes. This is the
  implicit "no graph help" path.

Then `_enforce_diversity` (line 159) ensures at least
`diversity_min_per_plan` (default 1) chunk survives from each contributing
plan, then fills the rest by similarity. Final result is re-sorted by
similarity.

**The join between graph and vector store is the `req_id` metadata
field.** The builder stores it on every Requirement node; the chunk
builder stores it on every chunk; the retriever uses it as the filter.
This is the concrete mechanism that makes "targeted RAG" actually scoped
(TDD §7.4).

### 6.5 Stage 5 — ContextBuilder (`src/query/context_builder.py`)

This is the **other place where the graph is read at query time.** The
builder takes retrieved chunks and enriches each one by re-visiting its
graph node:

`_enrich_chunk` (line 163) reads `chunk.graph_node_id` and pulls from the
graph:

- `hierarchy_path` attribute from the Requirement node (line 173)
- `_get_parent_text` (line 194): walks incoming `parent_of` edges to get
  the parent Requirement's title + text
- `_get_standards_context` (line 207): walks outgoing
  `references_standard` edges, pulls `text`, `spec`, `section`,
  `release_num`, `title` from each target Standard_Section node
- `_get_related_ids` (line 232): walks outgoing `depends_on` edges and
  returns the target requirements' `req_id`s

These four graph lookups become explicit sections in the rendered prompt
(`_format_context`, line 243):

```
--- Requirement i of N ---
MNO: VZW | Release: 2026_feb | Plan: LTEDATARETRY | Section: 4.2.1
Req ID: VZ_REQ_LTEDATARETRY_7748
Path: SCENARIOS > EMM SPECIFIC PROCEDURES > ATTACH REQUEST > …
Parent context: …

<stripped chunk text>

[Referenced Standard: 3GPP TS 24.301, Section 5.5.1.2.6 (Release 11)]
Title: …
<std section text, truncated to 2000 chars>

Depends on: VZ_REQ_LTESMS_1234, VZ_REQ_LTEDATARETRY_7750
[Relevance score: 0.2341]
```

System prompts are keyed on the query type
(`_SYSTEM_PROMPTS` dict at line 58). Every prompt appends a `_CITATION_RULES`
block and a `_FEW_SHOT_EXAMPLE` to enforce inline req ID citations.

At the end of the context, the builder appends a REMINDER block listing
the req IDs that appear in the context and telling the model to cite them
inline (line 314-324). This is a defensive measure because the
synthesizer models sometimes skip citations without it.

### 6.6 Stage 6 — Synthesizer

Default is `MockSynthesizer` (`src/query/pipeline.py:72`). Real LLM
synthesis is optional and injected. The graph's job is done before this
stage runs.

---

## 7. Gap Analysis: Design vs. Implementation

Pulling together the divergences noted inline above:

| Area | TDD says | Code does |
|------|----------|-----------|
| Test cases | `Test_Plan`, `Test_Case` nodes; `tested_by`/`tests` edges drive traceability queries | Deferred. `TRACEABILITY` query type falls through to GENERAL. |
| Cross-release | `version_of` edges with `change_type`; `succeeds` edges; `is_latest` flag | Deferred. `RELEASE_DIFF` query type falls through to GENERAL. "Latest" is computed by reverse-lex sort. |
| Standards delta | Typed edges `defers_to` / `constrains` / `overrides` / `extends` with pre-computed `delta_summary` | Flattened to a single `references_standard` edge. Deltas must be re-derived by the LLM from raw text. |
| Cross-plan `depends_on` | Req → Req (specific target requirement) | Req → Plan (coarse target). Target requirement is selected by RAG, not by the edge. |
| Feature `maps_to` | Curated per-requirement mapping | Coarse — every req in a primary/referenced plan maps to the feature. |
| `concept_link` | LLM-tagged similarity edges | Deferred. |
| Query analyzer | LLM-based intent extraction | Keyword-based `MockQueryAnalyzer` by default. |
| Synthesizer | LLM | `MockSynthesizer` by default. |

None of these gaps are blocking for the PoC — the graph is still the
structural backbone. But anything in TDD §8 that depends on test-case
nodes (`8.1.6`, `8.2.*`, `8.3.*` partially) or release-diff edges
(`8.1.5`) is not actually wired up yet.

---

## 8. Concrete Example — Walking a Query Through the Code

Query: *"What is the T3402 timer behavior in VZW Data Retry?"*

1. **Stage 1 (`MockQueryAnalyzer`).**
   - MNO keyword "VZW" → `mnos = ["VZW"]`
   - Plan keyword "data retry" → `plan_ids = ["LTEDATARETRY"]`
   - Feature keyword "t3402" → `likely_features = ["TIMER_MANAGEMENT"]`
     (via `_FEATURE_KEYWORDS` line 69)
   - No 3GPP spec pattern, no `VZ_REQ_...` id, so `entities = []`
   - `query_type = SINGLE_DOC` (single MNO, single plan).

2. **Stage 2 (`MNOReleaseResolver`).**
   - `_available = {"VZW": ["2026_feb", …]}` (built from Release nodes).
   - No release specified → defaults to `2026_feb`.
   - Output: `scoped_mnos = [MNOScope("VZW", "2026_feb")]`.

3. **Stage 3 (`GraphScoper`).**
   - Entity lookup: empty (no req IDs in query).
   - Feature lookup: finds `feature:TIMER_MANAGEMENT`, walks predecessors
     along `maps_to`. Because mapping is coarse (§4.4), this returns every
     requirement in every plan that is `primary_in` or `referenced_in`
     TIMER_MANAGEMENT — filtered to VZW/2026_feb. Easily dozens or
     hundreds of nodes.
   - Plan lookup: `plan_ids=["LTEDATARETRY"]` is set, but *only* runs if
     seed_nodes is empty (line 116). Here feature lookup already
     populated seeds, so plan lookup is skipped.
   - Traversal: SINGLE_DOC → edges `depends_on, parent_of,
     references_standard`, depth 1. Expansion stays inside VZW/2026_feb
     via scope check.

4. **Stage 4 (`RAGRetriever`).**
   - Candidate req IDs → ChromaDB `where={"req_id": {"$in": [...]}}`.
   - Top-10 by similarity to the embedded query "What is the T3402 timer
     behavior…".
   - `_enforce_diversity` keeps ≥1 chunk per plan (here everything is
     LTEDATARETRY, so no real effect).

5. **Stage 5 (`ContextBuilder`).**
   - For each chunk, re-visit the graph node:
     - `hierarchy_path` from the node's attribute
     - incoming `parent_of` → parent title + text
     - outgoing `references_standard` → the 3GPP section text (if the
       standards pipeline populated it)
     - outgoing `depends_on` → related req IDs
   - System prompt is `_SYSTEM_PROMPTS[SINGLE_DOC]` + citation rules +
     few-shot.

6. **Stage 6.**
   - Synthesizer sees every candidate requirement labeled with MNO,
     release, plan, section, hierarchy path, referenced 3GPP text, and
     an explicit "cite these req IDs" reminder.

### Where the graph actually changed the outcome

The graph contributed four concrete things in this trace:

1. **Scoping.** Without Stage 3 candidates, Stage 4 would fall back to
   `_metadata_retrieve`: any VZW/2026_feb chunk is eligible. With
   candidates, only chunks whose `req_id` is in the TIMER_MANAGEMENT
   feature set are eligible — a roughly 10× reduction in search space.
2. **Parent context.** `_get_parent_text` walks `parent_of` edges that
   no chunk contains — the chunk has only its own section's text.
3. **Standards text.** The 3GPP 24.301 §5.5.1.2.6 text enters the prompt
   because `references_standard` leads to a Standard_Section node whose
   `text` attribute was populated during standards ingestion. The chunk
   itself has no 3GPP text.
4. **Dependency annotations.** `Depends on: …` line at the end of each
   requirement comes from outgoing `depends_on` edges.

A pure-RAG run on the same query (via `_bypass_graph=True`) would skip
(1)-(4).

---

## 9. Interfaces and Pointers

- Schema (nodes/edges, ID helpers): `src/graph/schema.py`
- Builder: `src/graph/builder.py` (entry `build()` at line 77)
- Query pipeline: `src/query/pipeline.py` (entry `query()` at line 77)
  - Analyzer: `src/query/analyzer.py`
  - Resolver: `src/query/resolver.py`
  - Scoper: `src/query/graph_scope.py` (traversal rules line 33-77)
  - Retriever: `src/query/rag_retriever.py`
  - Context builder: `src/query/context_builder.py`
- Query data models: `src/query/schema.py`
- Chunk builder (produces the `req:<req_id>` chunks the graph joins to):
  `src/vectorstore/chunk_builder.py`
- Full design (for what's not yet implemented): `TDD_Telecom_Requirements_AI_System.md`
