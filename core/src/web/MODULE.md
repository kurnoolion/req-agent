# web

**Purpose**
FastAPI + Bootstrap 5 + HTMX Web UI for non-CLI team members (D-008). Provides pipeline submission with SSE-streamed logs, a persistent job queue, a shared-folder browser with Windows↔Linux path translation, a query console, a corrections editor, and a metrics dashboard (D-009). Runs behind an authenticating reverse proxy (`root_path` support; no in-app auth per D-016), works fully offline (vendored Bootstrap / Icons / HTMX), and never blocks a request on metric writes. Serves FR-16 (in-browser correction editing), FR-19 (eight surfaces: pipeline / SSE / job queue / folder browse / query / env CRUD / corrections / metrics), FR-20 (no npm/JS build), FR-28 (env_dir via Web UI form), FR-29 (state/ for runtime DBs per D-022); covers NFR-3 (vendored static assets), NFR-10 (fire-and-forget metrics middleware), NFR-11 (5-category SQLite metrics), NFR-12 (`/proc` + `nvidia-smi` sampling, no `psutil`).

**Public surface**
- App (app.py):
  - `app: FastAPI` — the ASGI application; wires middleware, static mounts, routers, templates
- Config (config.py):
  - `WebConfig` — host, port, root_path, path_mappings, ollama_url, default_model, env_dir, plus DB-path overrides `jobs_db` / `metrics_db` / `feedback_db`; `from_dict()`, `env_dir_path()`, `state_path()`, `jobs_db_path()`, `metrics_db_path()`, `feedback_db_path()` (per D-022; override-aware)
  - `PathMapping` — `(windows, linux, label)` entry
  - `EnvJsonConfig` — schema for the optional `config/env.json` layer (env-related fields: `env_dir`, `jobs_db`, `metrics_db`, `feedback_db`); `load(path=None)` with malformed/missing tolerance
  - `load_config(path=None) -> WebConfig` — resolves env_dir (web.json > $ENV_DIR > env.json) and per-DB overrides (CLI / env var > env.json > computed default) in one call
  - `DEFAULT_CONFIG_PATH`, `DEFAULT_ENV_JSON_PATH` — module-level constants pointing at `config/web.json` and `config/env.json`
- Jobs (jobs.py):
  - `Job` dataclass — id, job_type (`pipeline | query | eval`), status, pipeline/query fields, progress, log_lines, result, error
  - `JobQueue(db_path)` — aiosqlite-backed queue; `init_db()`, submit / update / list / cancel / load / append-log
- Metrics (metrics.py):
  - `MetricRecord` — timestamp, category (`request | llm | pipeline | resource | eval`), name, value, unit, tags
  - `MetricsStore(db_path)` — aiosqlite store with indexes on category / name / timestamp; `init_db()`, `record()`, query helpers
- Feedback (feedback_db.py):
  - `FeedbackStore(db_path)` — aiosqlite store for the Test page's free-form Q&A + thumbs-up/down + comment log; `initialize()`, `record_qa()` (returns row id), `record_feedback(row_id, vote, free_form_feedback)`, `get_row()`, `list_recent()`. Surface for offline review of LLM hallucinations (D-043 driver).
- Config store (config_db.py) [D-053]:
  - `ConfigStore(db_path)` — synchronous SQLite-backed user-config store; values JSON-encoded; threadsafe via internal lock. Public methods: `get(module, key)`, `get_module(module)`, `get_all()`, `set(module, key, value, updated_by)`, `delete(module, key)`, `apply_to_caches()` (overlay every stored value onto the cached `LLMConfigFile` / `RetrievalConfig` instances at lifespan startup), `reapply_one(module, key)` (cheaper single-field overlay used after each save).
- Config schema (config_schema.py) [D-053]:
  - `ConfigField` — per-knob metadata: `module`, `key`, `label`, `kind` (`bool` / `string` / `int` / `float` / `enum` / `password` / `dict_by_query_type`), `category` (`feature` / `value` / `tunable`), `choices` for enums, `value_kind` for per-type maps, `help` text.
  - `ConfigSection` — section grouping (LLM & Embedding, Retrieval & Grouping); `CONFIG_SECTIONS: list[ConfigSection]` is the page's authoritative schema.
  - `find_field(module, key) -> ConfigField | None`, `all_fields() -> list[ConfigField]` — accessors.
- Markdown rendering (markdown_render.py):
  - `render_markdown(text) -> Markup` — converts LLM answer markdown to Jinja-safe HTML (headers, bullets, **bold**, *italic*, fenced code, tables, `nl2br`). Registered as the `md` Jinja filter on `templates.env`. Strips dangerous tags defensively before parsing (script / style / iframe / object / embed / svg-with-onclick / math).
- DOCX preview rendering (docx_html_render.py):
  - `render_docx_html(file_path) -> str` — emits an HTML fragment for the Bootstrap annotation harness. Walks docx body in `DOCXExtractor`'s order and applies the same skip rules (empty paragraphs, degenerate tables) so every emitted element's `data-block-idx` matches the IR's `ContentBlock.position.index`. Tables also emit `data-row-idx` per body row for row-range annotations.
- Annotation schema (bootstrap_schema.py):
  - `validate_annotation_file(payload) -> dict` — server-side validator for `<env_dir>/annotations/<plan>_annotations.json` per `cline-playbooks/annotation-schema.md`; returns sanitized payload (extra fields stripped) or raises `AnnotationValidationError` with a per-field error list.
  - `KINDS` — 14 kinds: 8 structural (`section_heading`, `req_id`, `toc`, `strikethrough`, `version_history`, `definitions`, `applicability`, `priority`), 5 reference (`reference_intra_doc`, `reference_cross_doc`, `reference_spec`, `reference_list`, `reference_list_entry`), and 1 user-override (`remove`, [D-061]).
  - `SPEC_REFERENCE_STYLES` (`direct` / `indirect`) — required field for `reference_spec` kind.
  - `REFERENCE_LIST_NUMBERING_STYLES`, `REFERENCE_LIST_LAYOUTS`, `STRIKETHROUGH_SUBKINDS`, `STRIKETHROUGH_VISUALS`, `TOC_PATTERN_HINTS`, `DEFINITIONS_LAYOUTS`, `REQ_ID_PLACEMENTS`, `APPLICABILITY_POSITIONS`, `VERSION_HISTORY_SUBTYPES` — authoritative enum constants.
  - `TARGET_KEYS_BY_KIND` — per-kind allowed keys for the optional ground-truth `target` dict (intra_doc: section_number/req_id; cross_doc: +plan_id; reference_spec: spec/section/ref_number; reference_list_entry: spec/section). Unknown keys silently stripped on save.
  - `NOTES_MAX_CHARS`, `SCHEMA_VERSION` — caps.
  - `AnnotationValidationError` — raised on validation failure; carries `errors: list[str]`.
- `MetricsMiddleware` (middleware.py) — captures every request's timing and error count; fire-and-forget
- `PathMapper(mappings)` (path_mapper.py) — `to_linux()`, `to_windows()`; translates Windows UNC paths to Linux mount points
- `ResourceSampler` (resource_sampler.py) — background task sampling CPU / memory / disk / GPU via `/proc` and `nvidia-smi` (no `psutil` dependency)
- Routers (routes/): dashboard, environments, pipeline, jobs, query, corrections, files, metrics_route, parse_review (Parse page — two tabs: **Bootstrap** annotation harness with `GET /parse-review/bootstrap/docs`, `GET /parse-review/bootstrap/<doc_id>/view`, `GET|POST /parse-review/bootstrap/<doc_id>/annotations` writing `<env_dir>/annotations/<plan>_annotations.json` atomically; **Review** post-parse 3-pane), req_browser (Requirement Browser), resolve_review (Resolve Review UI), playground (Test page — `POST /api/test/ask`, `POST /api/test/synthesize-group` for D-049 disambiguation user-pick path, `POST /api/test/feedback`), config_route (Config page — `GET /config`, `POST /api/config/save`; D-053) — each mounted via `app.include_router`
- App state (set up in `lifespan`): `app.state.job_queue`, `app.state.metrics`, `app.state.feedback_store`, `app.state.path_mapper`, `app.state.config_store` (ConfigStore | None — None when `--config-db` is unset), `app.state.query_pipeline` (cached after first build; saving via `/api/config/save` sets it back to None so the next query rebuilds with the new resolved values).
- CLI launcher (`if __name__ == "__main__"` in app.py): `--env-dir`, `--host`, `--port`, `--jobs-db`, `--metrics-db`, `--feedback-db`, `--config-db` (each maps to a corresponding `NORA_*_DB` / `ENV_DIR` env var so the uvicorn-reload worker re-import sees the same resolution).
- Static + Templates: vendored under `static/` and `templates/` — no CDN at runtime

**Invariants**
- `MetricsMiddleware` is **fire-and-forget** — it never blocks or crashes a response. Metric failures are swallowed at `logger.debug`.
- Zero npm / JS build step. Server-side jinja2 + HTMX partials only; Bootstrap 5 + Bootstrap Icons + HTMX are **vendored** under `static/`. Runtime never fetches from a CDN.
- **Reverse-proxy compatible**: `root_path` is injected into every template context via `_template_response()`. Links built with `url_for` or prefixed by `{{ root_path }}` work behind a sub-path proxy mount.
- SQLite uses WAL journal mode (both jobs and metrics DBs) — supports concurrent reads while a background job writes.
- Jobs and metrics DBs are separate files (`<env_dir>/state/nora.db`, `<env_dir>/state/nora_metrics.db` per D-022) — metrics can be truncated for retention without touching job history.
- `PathMapper` is case-insensitive for Windows paths (UNC paths are not case-sensitive); it returns `None` when no mapping matches — callers surface that as a user error, not a 500.
- Resource sampler runs on a 30s interval, reads CPU from `/proc/stat`, memory from `/proc/meminfo`, GPU via `nvidia-smi` subprocess — deliberately dependency-free because the host may be locked down.
- No proprietary document content in metric tags, job log lines sent to SSE, or error-message templates. Verbose logs persist to disk; chat-facing surfaces stay clean (D-012).
- **Config-page DB layer in resolver chain** [D-053]: when `--config-db` / `$NORA_CONFIG_DB` is set, lifespan startup instantiates `ConfigStore` and calls `apply_to_caches()`, which overlays every stored value onto the cached `LLMConfigFile` / `RetrievalConfig` instances. The existing `resolve_*` functions in `core/src/env/config.py` then automatically pick up the new tier — no plumbing changes elsewhere. Effective resolver chain becomes `CLI > env var > ConfigStore (DB) > config/*.json > defaults`. `POST /api/config/save` writes to the DB, calls `reapply_one` to refresh the cache, and sets `app.state.query_pipeline = None` so the next query rebuilds with the new resolved values.
- **Markdown renderer strips dangerous HTML before parsing**: `render_markdown` removes `<script>` / `<style>` / `<iframe>` / `<object>` / `<embed>` / `<svg>` / `<math>` tags (paired and self-closing) before invoking the markdown library. LLM answer text on the Test page goes through this filter; raw chunk text in the click-to-expand fragment view deliberately doesn't (the indexed body may contain literal markdown syntax that's part of the requirement, e.g. `**MUST**` in 3GPP-style specs).
- **Logging configured at module-import time**, not just inside the `if __name__ == "__main__":` launcher block. Required because `uvicorn.run(reload=True)` spawns a worker that re-imports the module but never executes the launcher block; without basicConfig at import, the worker's loggers default to WARNING and silently drop every `logger.info(...)` in the request path (verification lines like `Web LLM resolved`, `[Query knobs]`, `ConfigStore active` would never reach stderr).
- **Bootstrap-tab DOCX renderer is index-aligned with the extractor**: `docx_html_render.render_docx_html` walks the docx body in `DOCXExtractor.extract`'s order and applies the same skip rules (empty paragraphs and degenerate single-empty-column tables consume no index). This guarantees every `data-block-idx` in the rendered HTML corresponds to a real `ContentBlock.position.index` in the saved IR — a regression here would silently misalign every annotation.
- **Bootstrap reference detection is decoupled from resolution**: annotation kinds capture the *source-token shape* of references (5 kinds: `reference_intra_doc`, `reference_cross_doc`, `reference_spec` with `style=direct|indirect`, `reference_list`, `reference_list_entry`). The optional `target` dict is **ignored by Cline's rule derivation** — it carries resolver-eval ground truth only. Indirect spec citations (`[5]`) flow through a two-step path the parser already supports for `definitions`: section-level annotation marks the references list; per-entry pattern populates a `reference_list_map: dict[int, {spec, section?}]` on the parsed tree; the resolver looks up the bracketed number in that map at resolve time. This split keeps detection rules portable across MNOs and lets resolution evolve independently.

**Key choices**
- FastAPI over Streamlit / Gradio because the UI needs fine-grained routing (corrections, files, jobs) and reverse-proxy deployment — SESSION_SUMMARY §19.
- HTMX over a SPA framework — dramatically less JS, server renders HTML fragments, state lives in SQLite. Matches the "no npm build" invariant.
- `asyncio.create_task()` for background jobs + SSE for log streaming — one process, no broker, deploys as a single service.
- `ResourceSampler` reads `/proc` directly rather than importing `psutil` — one less pip install on restricted hosts and works inside containers without privileges.
- Separate metrics DB so the metrics retention / truncation policy can be aggressive without touching the job history.
- Ollama URL and default model live in `WebConfig` rather than env vars — the UI exposes them in settings; `PipelineContext` reads the same config when it creates a provider.
- **`/config` page + ConfigStore as the user-editing surface for the resolver chain** [D-053]: the page renders LLM and Retrieval knobs grouped by category (Features / Values / Tunable parameters) per `CONFIG_SECTIONS`. New `kind="dict_by_query_type"` schema field renders a per-`QueryType` table editor (used by `bm25_weight_by_type` today; pattern generalizes to the rest of Phase 4-migrate's per-type maps). Opt-in: when `--config-db` is unset, the page renders read-only with a notice and the resolver chain falls through to JSON files / defaults. See [`../query/RETRIEVAL.md`](../query/RETRIEVAL.md) §14 for the full configuration model.

**Non-goals**
- No multi-user auth / RBAC in v1. Production deployment runs behind an authenticating reverse proxy (D-016); when in-app authn is added, it's a distinct cross-cutting change, not a router plugin.
- Not a deployment platform. Production deployment (systemd / container / proxy config) is the user's responsibility; app only exposes the right ASGI entrypoint.
- No WebSocket real-time — SSE is sufficient for unidirectional log streaming; WS adds reconnect complexity we don't need.
- No state beyond SQLite + filesystem. Caches are HTTP-level (browser) or derived artifacts in `<env_dir>/out/`; there is no Redis, no memcached, no in-process dict that outlives a request.

<!-- BEGIN:STRUCTURE -->
_Alphabetical, regenerated by regen-map._


`app.py`
- `STATIC_DIR` — constant — pub
- `TEMPLATES_DIR` — constant — pub
- `WEB_DIR` — constant — pub
- `_duration_filter` — function — internal — Human-readable duration for a Job.
- `_start_time` — constant — internal
- `_template_response` — function — internal — Render a template with root_path injected into context.
- `app` — constant — pub
- `config` — constant — pub
- `dashboard` — function — pub
- `health_check` — function — pub
- `lifespan` — function — pub
- `logger` — constant — pub
- `templates` — constant — pub

`bootstrap_schema.py`
- `APPLICABILITY_POSITIONS` — constant — pub
- `AnnotationValidationError` — class — pub — Raised when an annotation payload fails schema validation.
  - `__init__` — constructor — internal
- `DEFINITIONS_LAYOUTS` — constant — pub
- `KINDS` — constant — pub
- `NOTES_MAX_CHARS` — constant — pub
- `REFERENCE_LIST_LAYOUTS` — constant — pub
- `REFERENCE_LIST_NUMBERING_STYLES` — constant — pub
- `REQ_ID_PLACEMENTS` — constant — pub
- `SCHEMA_VERSION` — constant — pub
- `SPEC_REFERENCE_STYLES` — constant — pub
- `STRIKETHROUGH_SUBKINDS` — constant — pub
- `STRIKETHROUGH_VISUALS` — constant — pub
- `TARGET_KEYS_BY_KIND` — constant — pub
- `TOC_PATTERN_HINTS` — constant — pub
- `VERSION_HISTORY_SUBTYPES` — constant — pub
- `_Ctx` — dataclass — internal
  - `err` — method — pub
- `_apply_kind_fields` — function — internal — Copy kind-specific optional fields from *ann* to *out* with validation.
- `_apply_target` — function — internal — Validate and copy the optional `target` dict for reference-* kinds.
- `_opt_bool` — function — internal
- `_opt_enum` — function — internal
- `_opt_int` — function — internal
- `_opt_str` — function — internal
- `_validate_annotation` — function — internal
- `_validate_region` — function — internal
- `validate_annotation_file` — function — pub — Validate a full annotation-file payload and return the sanitized form.

`config.py`
- `DEFAULT_CONFIG_PATH` — constant — pub
- `DEFAULT_ENV_JSON_PATH` — constant — pub
- `EnvJsonConfig` — dataclass — pub — Per-environment config loaded from `config/env.json`. All.
  - `load` — classmethod — pub
- `PROJECT_ROOT` — constant — pub
- `PathMapping` — dataclass — pub — Maps a Windows network path to a Linux mount point.
- `WebConfig` — dataclass — pub — Web application configuration.
  - `env_dir_path` — method — pub
  - `feedback_db_path` — method — pub — SQLite path for the Test page's question/answer/vote/feedback log.
  - `from_dict` — classmethod — pub
  - `jobs_db_path` — method — pub
  - `metrics_db_path` — method — pub
  - `state_path` — method — pub
- `_ENV_VAR_FEEDBACK_DB` — constant — internal
- `_ENV_VAR_JOBS_DB` — constant — internal
- `_ENV_VAR_METRICS_DB` — constant — internal
- `_resolve_db_path` — function — internal — Pick the highest-priority override for a DB path. Returns "".
- `load_config` — function — pub — Load config from JSON file, falling back to defaults.
- `logger` — constant — pub

`config_db.py`
- `ConfigStore` — class — pub — SQLite-backed key-value config store, scoped by (module, key).
  - `__init__` — constructor — internal
  - `_connect` — method — internal
  - `_init_schema` — method — internal
  - `apply_to_caches` — method — pub — Overlay every stored value onto the in-memory config caches.
  - `delete` — method — pub
  - `get` — method — pub — Return decoded value or None if absent.
  - `get_all` — method — pub — Return everything, indexed by (module, key) tuples.
  - `get_module` — method — pub — Return all (key → value) pairs for one module.
  - `reapply_one` — method — pub — After a single write, re-overlay just that value onto the.
  - `set` — method — pub — Upsert one (module, key) → value pair.
- `_JSON_DECODE_FALLBACK` — constant — internal
- `_SCHEMA_SQL` — constant — internal
- `_decode` — function — internal
- `_encode` — function — internal
- `logger` — constant — pub

`config_schema.py`
- `CONFIG_SECTIONS` — constant — pub
- `ConfigField` — dataclass — pub
- `ConfigSection` — dataclass — pub
- `_LLM_FIELDS` — constant — internal
- `_RETRIEVAL_FIELDS` — constant — internal
- `all_fields` — function — pub
- `find_field` — function — pub

`docx_html_render.py`
- `_HEADING_STYLE_PREFIX` — constant — internal
- `_all_runs_struck` — function — internal
- `_count_paragraph_images` — function — internal — Count inline images inside *para* that the extractor would emit.
- `_heading_level` — function — internal
- `_para_run_flags` — function — internal — Approximate (bold, italic, strikethrough) flags from runs.
- `_render_cell_runs` — function — internal — Render a single cell's runs as HTML; return (html, all_textful_struck).
- `_render_paragraph` — function — internal
- `_render_paragraph_inner` — function — internal — Render run-level HTML preserving per-run strike spans [D-060].
- `_render_table` — function — internal — Render a docx table as HTML, preserving per-cell run-level strikes [D-060].
- `render_docx_html` — function — pub — Render *file_path* as an HTML fragment with IR-aligned data attributes.

`feedback_db.py`
- `FeedbackStore` — class — pub — Async SQLite store for Test-page question/answer/feedback logs.
  - `__init__` — constructor — internal
  - `get_row` — method — pub — Read a single row by id (for testing / inspection).
  - `initialize` — method — pub — Create the schema if missing. Safe to call repeatedly.
  - `list_recent` — method — pub — Read the N most recent rows, optionally filtered by section.
  - `record_feedback` — method — pub — Update an existing Q&A row with the user's vote and/or.
  - `record_qa` — method — pub — Insert a new row at question-submission time. Returns the.
- `_SCHEMA` — constant — internal
- `logger` — constant — pub

`jobs.py`
- `Job` — dataclass — pub
- `JobQueue` — class — pub
  - `__init__` — constructor — internal
  - `append_log` — method — pub
  - `cancel` — method — pub
  - `cleanup_old` — method — pub
  - `get` — method — pub
  - `get_logs` — method — pub
  - `get_logs_with_numbers` — method — pub
  - `get_meta` — method — pub — Get job metadata without loading log lines.
  - `init_db` — method — pub
  - `list_jobs` — method — pub
  - `submit` — method — pub
  - `update_status` — method — pub
- `_IDX_JOBS_CREATED` — constant — internal
- `_IDX_JOBS_STATUS` — constant — internal
- `_IDX_LOGS_JOB` — constant — internal
- `_JOBS_SCHEMA` — constant — internal
- `_LOGS_SCHEMA` — constant — internal
- `_now_iso` — function — internal
- `_row_to_job` — function — internal

`markdown_render.py`
- `_DANGEROUS_TAG_OPEN_RE` — constant — internal
- `_DANGEROUS_TAG_RE` — constant — internal
- `_MD_EXTENSIONS` — constant — internal
- `render_markdown` — function — pub — Convert markdown source to HTML, return Jinja-safe Markup.

`metrics.py`
- `MetricRecord` — dataclass — pub
- `MetricsStore` — class — pub
  - `__init__` — constructor — internal
  - `_agg_for` — method — internal
  - `_latest_value` — method — internal
  - `_pipeline_stage_summary` — method — internal
  - `cleanup_old` — method — pub
  - `compact_report` — method — pub — Compact pasteable summary in RPT style.
  - `init_db` — method — pub
  - `query` — method — pub
  - `record` — method — pub
  - `record_batch` — method — pub
  - `summary` — method — pub — Aggregates: count, avg, min, max, p95 per metric name.
- `_IDX_CATEGORY` — constant — internal
- `_IDX_CAT_NAME_TS` — constant — internal
- `_IDX_NAME` — constant — internal
- `_IDX_TIMESTAMP` — constant — internal
- `_METRICS_SCHEMA` — constant — internal
- `_now_iso` — function — internal
- `logger` — constant — pub

`middleware.py`
- `MetricsMiddleware` — class — pub
  - `dispatch` — method — pub
- `_record_request_metric` — function — internal
- `logger` — constant — pub

`path_mapper.py`
- `PathMapper` — class — pub — Translates paths between Windows UNC and Linux mount conventions.
  - `__init__` — constructor — internal
  - `is_within_roots` — method — pub — Security check: ensure the resolved path is within a configured root.
  - `list_roots` — method — pub — Return available roots with both path representations and labels.
  - `resolve` — method — pub — Smart resolve: detect Windows paths and convert; otherwise treat as Linux.
  - `to_linux` — method — pub — Convert a Windows UNC path to a Linux path.
  - `to_windows` — method — pub — Convert a Linux path to a Windows UNC path for display.
- `_is_subpath` — function — internal — Return True if *path* is strictly under *parent*.
- `_looks_like_windows` — function — internal — Heuristic: starts with \ or a drive letter like C:\.
- `_normalize_win` — function — internal — Normalize a Windows path: forward slashes to backslashes, strip trailing.

`resource_sampler.py`
- `_DEFAULT_INTERVAL` — constant — internal
- `_prev_cpu_idle` — constant — internal
- `_prev_cpu_total` — constant — internal
- `_read_cpu_percent` — function — internal — Read CPU utilization from /proc/stat using delta between calls.
- `_read_disk_usage` — function — internal — Read disk usage for a path. Returns (used_gb, total_gb).
- `_read_gpu_info` — function — internal — Read GPU utilization via nvidia-smi. Returns None if unavailable.
- `_read_memory_gb` — function — internal — Read RAM from /proc/meminfo. Returns (used_gb, total_gb).
- `_sample_once` — function — internal
- `_sampler_loop` — function — internal
- `logger` — constant — pub
- `start_resource_sampler` — function — pub — Start the background sampler and return its task handle.

`routes/config_route.py`
- `_coerce` — function — internal — Convert a form string to the field's typed value. Empty string.
- `_current_dict_by_query_type` — function — internal — Build the {query_type: value} dict for a dict_by_query_type.
- `_current_value` — function — internal — Read the live effective value for a field via the resolver chain.
- `config_page` — function — pub
- `config_save` — function — pub — Persist edits, invalidate caches, clear cached pipeline.
- `logger` — constant — pub
- `router` — constant — pub

`routes/corrections.py`
- `ENVIRONMENTS_DIR` — constant — pub
- `PROJECT_ROOT` — constant — pub
- `_list_envs_with_status` — function — internal
- `_load_env` — function — internal
- `_safe_name` — function — internal
- `corrections_index` — function — pub
- `logger` — constant — pub
- `profile_discard` — function — pub
- `profile_editor` — function — pub
- `profile_save` — function — pub
- `profile_start` — function — pub
- `report_page` — function — pub
- `report_text` — function — pub
- `router` — constant — pub
- `taxonomy_discard` — function — pub
- `taxonomy_editor` — function — pub
- `taxonomy_save` — function — pub
- `taxonomy_start` — function — pub

`routes/dashboard.py`
- `dashboard_jobs_partial` — function — pub
- `dashboard_stats` — function — pub
- `dashboard_status_partial` — function — pub
- `logger` — constant — pub
- `router` — constant — pub

`routes/environments.py`
- `ENVIRONMENTS_DIR` — constant — pub
- `PROJECT_ROOT` — constant — pub
- `_list_environments` — function — internal
- `_stages_for_template` — function — internal
- `create_environment` — function — pub
- `delete_environment` — function — pub
- `environments_list` — function — pub
- `environments_new` — function — pub
- `logger` — constant — pub
- `router` — constant — pub

`routes/files.py`
- `_build_breadcrumbs` — function — internal
- `_find_root_label` — function — internal
- `_human_size` — function — internal
- `browse` — function — pub
- `file_listing_partial` — function — pub
- `files_page` — function — pub
- `logger` — constant — pub
- `router` — constant — pub

`routes/jobs.py`
- `TERMINAL_STATUSES` — constant — pub
- `cancel_job` — function — pub
- `job_detail` — function — pub
- `job_log_stream` — function — pub
- `jobs_list` — function — pub
- `jobs_table_partial` — function — pub
- `logger` — constant — pub
- `router` — constant — pub

`routes/metrics_route.py`
- `logger` — constant — pub
- `metrics_compact` — function — pub
- `metrics_page` — function — pub
- `metrics_resource_partial` — function — pub — HTMX partial: refreshes the resource gauges.
- `metrics_summary` — function — pub
- `router` — constant — pub

`routes/parse_review.py`
- `_annotations_dir` — function — internal
- `_annotations_path` — function — internal
- `_atomic_write_json` — function — internal
- `_build_annotated_blocks` — function — internal — Load DocumentIR + ParseLog and return (blocks, log, error_message).
- `_list_docs` — function — internal — Return doc IDs that have at least a parse log OR an IR file.
- `_list_docx_inputs` — function — internal — List DOCX files under <env_dir>/input/<MNO>/<RELEASE>/ available for annotation.
- `_load_log` — function — internal
- `_load_or_default_review` — function — internal
- `_parse_log_dir` — function — internal
- `_resolve_docx_path` — function — internal
- `bootstrap_list_docs` — function — pub
- `bootstrap_load_annotations` — function — pub
- `bootstrap_save_annotations` — function — pub
- `bootstrap_view` — function — pub
- `logger` — constant — pub
- `parse_review_index` — function — pub
- `parse_review_report` — function — pub
- `parse_review_save` — function — pub
- `parse_review_view` — function — pub
- `router` — constant — pub

`routes/pipeline.py`
- `ENVIRONMENTS_DIR` — constant — pub
- `PROJECT_ROOT` — constant — pub
- `_list_environments` — function — internal — Scan environments/*.json and return summary dicts.
- `_record_stage_metrics` — function — internal — Record pipeline stage metrics to MetricsStore (fire-and-forget safe).
- `_stages_for_template` — function — internal — Build stage list for dropdown rendering.
- `logger` — constant — pub
- `pipeline_page` — function — pub
- `router` — constant — pub
- `run_pipeline_background` — function — pub — Execute pipeline stages in a background task.
- `submit_pipeline` — function — pub

`routes/playground.py`
- `_SECTIONS` — constant — internal
- `_run_query_for_test` — function — internal — Adapt the existing /query pipeline runner into a dict shape.
- `logger` — constant — pub
- `playground_ask` — function — pub — Submit a question, run the query pipeline, log the Q&A row,.
- `playground_feedback` — function — pub — Update an existing Q&A row with the user's vote / comment.
- `playground_page` — function — pub
- `playground_synthesize_group` — function — pub — Step 3c — user picked a group from a disambiguation response.
- `router` — constant — pub

`routes/query.py`
- `PROJECT_ROOT` — constant — pub
- `_DEFAULT_MAX_DISTANCE_THRESHOLD` — constant — internal
- `_MAX_DISTANCE_THRESHOLD_ENV_VAR` — constant — internal
- `_PipelineBuildError` — class — internal — Raised by `_build_pipeline` when prerequisites aren't met.
- `_build_llm_from_env_or_default` — function — internal — Construct the LLM provider for /query and /test.
- `_build_pipeline` — function — internal — Construct a QueryPipeline + LLM. Heavy: loads graph (~10MB),.
- `_config_store_get` — function — internal — Best-effort read from app.state.config_store. Returns None if.
- `_find_env_config_for_web` — function — internal — Locate the env JSON whose `env_dir` matches the Web UI's.
- `_get_or_build_pipeline` — function — internal — Return (pipeline, llm) cached on `app.state`. First call pays.
- `_graph_path` — function — internal — Resolve `<env_dir>/out/graph/knowledge_graph.json`. The Web UI.
- `_pipeline_build_lock` — constant — internal
- `_record_llm_metrics` — function — internal — Record LLM call metrics to MetricsStore (fire-and-forget safe).
- `_resolve_max_distance_threshold` — function — internal — Return the threshold to pass to QueryPipeline. None disables it.
- `_resolve_top_k_cap` — function — internal — Resolve the user-configured Top-K cap from the ConfigStore.
- `_run_query_sync` — function — internal — Run the query pipeline synchronously (called via asyncio.to_thread).
- `_vectorstore_dir` — function — internal — Resolve `<env_dir>/out/vectorstore/`.
- `logger` — constant — pub
- `query_page` — function — pub
- `query_result` — function — pub
- `router` — constant — pub
- `run_query_background` — function — pub — Execute query in a background task.
- `submit_query` — function — pub

`routes/req_browser.py`
- `_build_tree_hierarchy` — function — internal — Convert flat requirement list into nested tree (child_nodes populated).
- `_list_docs` — function — internal
- `_load_req` — function — internal
- `_load_tree_flat` — function — internal
- `_load_xrefs` — function — internal
- `_parse_dir` — function — internal
- `_parse_str_list` — function — internal
- `_refs_for_req` — function — internal — Return refs sourced from req_id, grouped by type.
- `_resolve_dir` — function — internal
- `logger` — constant — pub
- `req_browser_compare` — function — pub
- `req_browser_detail` — function — pub
- `req_browser_index` — function — pub
- `req_browser_tree` — function — pub
- `router` — constant — pub

`routes/resolve_review.py`
- `_TEXT_PREVIEW` — constant — internal
- `_build_ref_rows` — function — internal — Build enriched ref rows for each of the three ref types.
- `_build_req_index` — function — internal — Return req_id -> {text, section, title} from the parsed tree.
- `_list_docs` — function — internal
- `_load_or_default_review` — function — internal
- `_parse_dir` — function — internal
- `_resolve_dir` — function — internal
- `_review_dir` — function — internal
- `logger` — constant — pub
- `resolve_review_index` — function — pub
- `resolve_review_report` — function — pub
- `resolve_review_save` — function — pub
- `resolve_review_view` — function — pub
- `router` — constant — pub
<!-- END:STRUCTURE -->

**Depends on**
[env](../env/MODULE.md), [models](../models/MODULE.md), [parser](../parser/MODULE.md), [pipeline](../pipeline/MODULE.md), [query](../query/MODULE.md), [resolver](../resolver/MODULE.md), [corrections](../corrections/MODULE.md).

**Depended on by**
None — top of the stack.

**Deferred**
- `ResourceSampler` class wrapper (deferred: current `start_resource_sampler()` function is functionally sufficient; class form would be a cosmetic refactor — revisit: if sampler state/lifecycle grows beyond the current single-task handle)
- Declare `llm`, `profiler`, `taxonomy`, `vectorstore` in Depends on (deferred: routes import schemas/configs across many peers; the right fix is likely to route through `pipeline`/`query` rather than expand Depends on — revisit: when refactoring routes to reduce peer coupling)
