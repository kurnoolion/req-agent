# SIRA setup + verify

Step-by-step to stand up the `sira` strand's sandbox end-to-end. Layout / file roles are in [`README.md`](README.md); this doc is purely procedural.

## Prerequisites

| | What | Notes |
|---|---|---|
| **Hardware** | NVIDIA GPU (Ampere or newer, ≥16 GB VRAM) | Required only if you run sglang locally. Our default path bypasses sglang via the FastAPI shim → proprietary LLM, so a CPU-only box **can** run BM25 + drive the LLM stages through the shim. The hard requirement is reduced to "whatever your proprietary LLM endpoint needs." |
| **OS** | Linux | SIRA's `pyproject.toml` pins `sys_platform == 'linux'`. WSL2 works. |
| **Python** | 3.12 | hard pin per SIRA's `requires-python` |
| **Rust toolchain** | `cargo`, `rustc` (stable) | Required to build the `bm25x` Rust extension. Install via `rustup`. |
| **uv** | `uv` package manager | SIRA's `pyproject.toml` declares custom indexes under `[tool.uv]`. `pip` alone won't resolve `sglang-kernel` / `flashinfer-jit-cache` correctly. |
| **Proprietary LLM** | Endpoint reachable from the box + working `customizations/llm/proprietary_provider.py` `complete()` implementation | Required for any non-trivial run. Until `complete()` is filled in, the shim returns 501. |

## One-time install

### 1. Clone SIRA into `sandbox/sira/`

```bash
cd $REPO_ROOT
git clone --depth 1 https://github.com/facebookresearch/sira.git sandbox/sira
```

`sandbox/sira/` is gitignored. To pull upstream updates later: `git -C sandbox/sira pull`. Re-run step 4 (install configs) after a pull in case prompt or config paths shifted.

### 2. Create the Python env

Pick the path that matches your machine.

#### 2a. Trimmed install — recommended on the work PC (no GPU + restricted network)

The four SIRA pipeline stages we actually run (`bm25`, `enrich_corpus`, `enrich_query`, `rerank`) import only `bm25x` (local Rust build via maturin), `aiohttp`, `hydra-core`, `omegaconf`, `polars`, `huggingface_hub` (just for the import — the download itself is skipped because our adapter writes `metadata.json`). They do **not** import `torch` / `sglang` / `transformers` / `flash-attn` / `flashinfer`. Those heavy deps in SIRA's `pyproject.toml` are for running sglang locally, which we bypass entirely via the FastAPI shim → proprietary LLM.

So we install only what's needed and tell `uv` to skip the rest:

```bash
cd sandbox/sira
uv venv .venv --python 3.12
source .venv/bin/activate

# Step 1: only the deps the four stages need + httpx for the shim's
# pass-through mode (step 5a) + FastAPI/uvicorn to run the shim
# + beir (--no-deps so it doesn't drag in torch/sentence-transformers)
# and beir's actual runtime needs (pytrec_eval, numpy).
#
# Polars note: the default `polars` wheel requires AVX2 / FMA / BMI1+2.
# On older/virtualized CPUs without those (common on corporate work
# PCs) it segfaults with "Illegal instruction" at runtime. The trimmed
# install below uses the compat wheel for safety. On a modern x86_64
# (Tiger Lake+, Zen2+) you can swap `polars[rtcompat]` for plain
# `polars` and gain SIMD acceleration — negligible for our data sizes.
uv pip install --system-certs \
    aiohttp hydra-core omegaconf 'polars[rtcompat]' maturin pybind11 \
    huggingface_hub fastapi uvicorn httpx \
    pytrec_eval numpy

# beir is used only for its EvaluateRetrieval metric wrapper. Full
# install pulls torch + sentence-transformers (~1 GB) which we don't
# need; --no-deps trims that out. pytrec_eval (above) is what
# EvaluateRetrieval actually calls under the hood; numpy is for its
# math.
uv pip install --system-certs --no-deps beir

# Step 2: install sira itself in editable mode, skipping its dep tree
# entirely. --no-deps means uv won't try to fetch torch / sglang / etc.
uv pip install --system-certs --no-deps -e .

# Activate the env + set PYTHONPATH + HF-offline env vars.
# Use OUR replacement; the upstream `sandbox.sh` is conda-only and
# errors with "conda env 'sira312' not found" on uv-based installs.
cd $REPO_ROOT
source sandbox/activate.sh
```

This avoids all three custom wheel indexes (`download.pytorch.org`, `docs.sglang.ai`, `flashinfer.ai`) — handy if your corporate firewall whitelists only PyPI.

#### 2b. Full install — once you have GPU + open network (e.g. DGX Spark)

```bash
cd sandbox/sira
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e .
cd $REPO_ROOT
source sandbox/activate.sh   # our replacement for upstream sandbox.sh (conda-only)
```

`uv pip install -e .` will reach out to three non-HF wheel indexes:

- `https://download.pytorch.org/whl/cu130/` (torch, torchvision)
- `https://docs.sglang.ai/whl/cu130/` (sglang-kernel)
- `https://flashinfer.ai/whl/cu130/` (flashinfer-jit-cache)

Plus regular PyPI for everything else.

**Corporate TLS interception** — if `uv pip install` fails with
`invalid peer certificate: UnknownIssuer` (the message names the
specific index, e.g. `docs.sglang.ai`), your network is re-signing
HTTPS with a corporate CA that isn't in `uv`'s bundled cert store.
Pass `--system-certs` to opt into the system CA store (which already
trusts the corporate CA, or the install wouldn't be possible at all):

```bash
uv pip install -e . --system-certs
```

Or set once for the shell session:

```bash
export UV_NATIVE_TLS=true   # uv >=0.5 reads this for every uv command
```

**Corporate firewall blocking download.pytorch.org** — if `uv` reports `torch was not found in the package registry` even with `--system-certs`, the corporate proxy is dropping requests to `download.pytorch.org` entirely (allowlist mode). You have two options:
- **Use the trimmed install (2a) instead** — we don't need torch anyway for our pipeline path.
- **Pre-download wheels on a connected box, transfer them**:
  ```bash
  # On connected box:
  uv pip download torch==2.9.1 torchvision==0.24.1 \
      --index-url https://download.pytorch.org/whl/cu130 -d wheels/
  uv pip download sglang-kernel \
      --index-url https://docs.sglang.ai/whl/cu130 -d wheels/
  # ... and so on for flashinfer-jit-cache + flash-attn-4

  # Transfer wheels/ to work PC, then:
  uv pip install --no-index --find-links wheels/ -e .
  ```

### 3. Build the `bm25x` Rust extension

The Python wrapper imports `bm25x` from the Rust crate via `maturin`. From inside `sandbox/sira/`:

```bash
cd src/sira/bm25x/python
maturin develop --release
cd $REPO_ROOT
```

Build time on a modest laptop: 2-5 min. CPU-only by default — set `cuda: true` in `scripts/configs/bm25/default.yaml` only if you have GPU and want it in BM25 too (not required; CPU bm25x is plenty fast for our corpus size).

### 4. Install NORA's configs + prompts into the clone

```bash
cd $REPO_ROOT
bash sandbox/install_configs.sh
```

Idempotent. Re-run after editing any of:
- `sandbox/sira_configs/{data,enrich,rerank}/nora.yaml`
- `sandbox/prompts/{doc,query,relevance}_requirement_v01.txt`

### 5. Point the shim at your LLM

The shim runs in one of two modes; pick the one that matches your deployment.

#### 5a. Pass-through mode — your proprietary LLM exposes OpenAI Chat Completions

If `https://your-llm/v1/chat/completions` already accepts the OpenAI request shape, the shim becomes a thin proxy: receives SIRA's request, forwards verbatim, returns the response. **No code to write** — `customizations/llm/proprietary_provider.py` is bypassed entirely.

Set these env vars in the shell that runs `uvicorn`:

```bash
export NORA_LLM_BASE_URL=https://your-internal-llm/v1   # base — shim appends /chat/completions
export NORA_LLM_API_KEY=<bearer-token>                  # optional; injected as `Authorization: Bearer …`
export NORA_LLM_MODEL=<actual-model-name>               # optional; overrides whatever SIRA sends in `model`
export NORA_LLM_TIMEOUT=300                             # optional; per-request seconds, default 300

# Corporate TLS only (skip on open networks):
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt # if your upstream uses a corporate-CA cert
# OR (escape hatch, internal endpoints only):
# export NORA_LLM_VERIFY_SSL=false

# Corporate HTTPS proxy bypass — if HTTPS_PROXY / HTTP_PROXY are set
# globally but your LLM endpoint is reachable directly, pick ONE:
export NO_PROXY="${NO_PROXY},your-llm-host.internal,localhost,127.0.0.1"
# OR (shim-local escape hatch — ignores all proxy env vars):
# export NORA_LLM_SKIP_PROXY=true
```

If `NORA_LLM_MODEL` is unset the shim forwards whatever SIRA puts in the `model` field. SIRA defaults to a sglang-style identifier (e.g. `qwen3.6-35b-a3b-fp8:h100`); set `NORA_LLM_MODEL` to the actual name your endpoint accepts.

These are the same env var names NORA's own LLM layer uses (D-044 / D-049), so if you already have NORA's OpenAI-compatible provider configured for the regular pipeline, the shim picks up the same config automatically.

#### 5b. Adapter mode — your proprietary LLM uses some other API

Leave `NORA_LLM_BASE_URL` **unset**. The shim falls back to calling `customizations/llm/proprietary_provider.py`'s `complete()`. Implement that method per your deployment — the signature must match the `LLMProvider` Protocol:

```python
def complete(self, prompt: str, system: str = "",
             temperature: float = 0.0, max_tokens: int = 4096) -> str
```

Return the completion text. See `customizations/llm/README.md` for guidance.

## Verify install

### A. Shim health

In one terminal, from `$REPO_ROOT` (env vars from step 5a or unset for 5b):

```bash
uvicorn sandbox.shim.openai_shim:app --port 8030
```

In another:

```bash
curl -s http://127.0.0.1:8030/healthz
# pass-through:  {"ok": true, "mode": "pass-through", "base_url": "...", "model_override": "...", "api_key_set": true}
# adapter:       {"ok": true, "mode": "adapter", "model": "...", "endpoint": "...", "calls": 0}

curl -s -X POST http://127.0.0.1:8030/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "test", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 16}'
```

Expected outcomes:
- **Pass-through + valid upstream**: 200 with the upstream OpenAI response forwarded verbatim.
- **Pass-through + bad upstream URL / auth**: 502 with `upstream error: ...` or `upstream NNN: ...`. Fix `NORA_LLM_BASE_URL` / `NORA_LLM_API_KEY`.
- **Adapter + `complete()` implemented**: 200 with an OpenAI-shaped envelope wrapping the provider's string.
- **Adapter + stub `complete()`**: 501 with `NotImplementedError`. Either implement step 5b *or* switch to 5a by setting `NORA_LLM_BASE_URL`.

### B. Adapter on real data

```bash
cd $REPO_ROOT
python -m sandbox.adapter.nora_to_beir \
    --env-dir <your_env_dir_with_parse_output> \
    --output sandbox/adapter/out/nora
```

Expect output like:

```
loaded N _tree.json file(s) from out/parse/
  corpus.jsonl: wrote N rows (skipped: 0 no-id, 0 duplicate)
  queries-test.jsonl: wrote 18 queries (5 have no expected_req_ids → not in qrels)
  qrels-test.jsonl: wrote 44 qrel rows
done — point SIRA at db_root=sandbox/adapter/out, data.name=nora
```

Inspect a row to sanity-check acronym expansion and structure:

```bash
head -1 sandbox/adapter/out/nora/raw/corpus.jsonl | python -m json.tool
```

### C. BM25 baseline on NORA (no LLM, fastest sanity check)

From the repo root:

```bash
source sandbox/activate.sh
cd sandbox/sira
python scripts/eval_bm25.py \
    data=nora \
    db_root=$(realpath ../adapter/out)
```

Runs the **prepare → bm25** stages only. Reads our adapter output, builds the BM25 index, evaluates recall@K against `qrels-test.jsonl`. Should complete in a minute or two with no LLM calls. Look for output under `sandbox/adapter/out/nora/eval/baseline/best.json`.

If this step works, the data pipeline is sound — every LLM-touching stage downstream just adds enrichment on top of this baseline.

### D. Full pipeline against the shim

```bash
# Terminal 1 — shim
cd $REPO_ROOT && uvicorn sandbox.shim.openai_shim:app --port 8030

# Terminal 2 — pipeline
cd $REPO_ROOT
source sandbox/activate.sh
cd sandbox/sira
python scripts/run_pipeline.py \
    data=nora \
    enrich=nora \
    rerank=nora \
    db_root=$(realpath ../adapter/out) \
    sglang.port=8030
```

Critical flags:
- `sglang.port=8030` — SIRA's hardcoded `http://127.0.0.1:{port}/v1/chat/completions` resolves to our shim.

**Concurrency**: `enrich/nora.yaml` and `rerank/nora.yaml` pin `concurrency: 1` (strict serial) because the work-PC corporate proxy throttles parallel requests — bursting hits 5xx and SIRA's retry backoff *increases* wall-clock. For unthrottled environments (DGX Spark with local sglang, or a workstation that hits the LLM endpoint directly without a corporate proxy), override on CLI: `enrich.concurrency=16 rerank.concurrency=8`. SIRA's upstream defaults are 4096 / 2048, calibrated for a local H100 sglang.

**Spawning sglang vs. using our shim:** SIRA's `run_pipeline.py` auto-detects whether a server is already running on `sglang.port` — it does `GET http://127.0.0.1:{port}/v1/models` and if that returns 200, logs *"Using existing LLM server on port {port}"* and proceeds. If the probe fails, it tries to spawn sglang locally (requires GPU + the full install). Our shim implements `/v1/models` for exactly this purpose, so **as long as `uvicorn` is running before you launch `run_pipeline.py`, SIRA picks up the shim automatically.** There's no `server.auto_start` flag — the detection is purely based on whether the port answers.

Output: per-stage eval JSONs at `sandbox/adapter/out/nora/eval/{baseline, doc-enrich, query-enrich, rerank}/best.json`. Compare `recall@10` across stages — that's the per-stage lift attributable to corpus enrichment / query enrichment / LLM reranking. Compare the final `recall@10` against NORA's A4 baseline (88.0% overall / 67.6% accuracy on the same 18-Q set).

### E. Per-query SIRA probe (NORA Test page "SIRA Retrieval" tab)

Interactive way to type a query and see SIRA's ranked retrieval. Available once verify-D has completed (SIRA's BM25 index + doc enrichments are on disk). Adds NO new SIRA modifications — just exposes per-query inference via a third local service.

**Architecture:**

```
┌─────────────────┐   POST /api/test/ask        ┌──────────────────────────┐
│  NORA web app   │ ───────────────────────────▶│  /test page              │
│  (port :8000 or │   { question, section=      │  (renders SIRA tab)      │
│   whatever)     │      "sira_retrieval" }     └──────────────────────────┘
└────────┬────────┘                                       │
         │ HTTP POST                                      │
         │ NORA_SIRA_QUERY_URL                            ▼
         ▼                                       ┌──────────────────────────┐
┌─────────────────┐   POST /sira-query           │  template renders        │
│  SIRA query     │ ◀────────────────────────────│  ranked req_ids + scores │
│  service        │   { query, top_k }           │  + text previews         │
│  (port :8040)   │                              └──────────────────────────┘
└────────┬────────┘
         │ HTTP POST × N
         ▼ /v1/chat/completions
┌─────────────────┐
│  Shim           │
│  (port :8030)   │
└────────┬────────┘
         │ (httpx via NORA_LLM_BASE_URL)
         ▼
┌─────────────────┐
│  Proprietary    │
│  LLM endpoint   │
└─────────────────┘
```

Three local services needed: shim (8030) + SIRA query service (8040) + NORA web (default whatever).

**Setup (in three terminals, all from repo root):**

```bash
# Terminal 1 — shim, same as everywhere else
source sandbox/activate.sh   # also exports SSL_CERT_FILE, NO_PROXY entries, etc.
# Make sure NORA_LLM_BASE_URL / NORA_LLM_API_KEY / NORA_LLM_MODEL are set here.
uvicorn sandbox.shim.openai_shim:app --port 8030

# Terminal 2 — SIRA query service
source sandbox/activate.sh
export NORA_SIRA_DB_ROOT=$(realpath sandbox/adapter/out)
# Optional knobs:
# export NORA_SIRA_TOP_K=10              # default top_k when caller doesn't supply
# export NORA_SIRA_RERANK_TOP_N=20       # candidates fed to LLM reranker
# export NORA_SIRA_MAX_DF_RATIO=0.05     # DF-filter cap for query expansion
# export NORA_SIRA_EXPANSION_WEIGHT=0.5  # BM25 expansion weight
uvicorn sandbox.sira_query.service:app --port 8040

# Verify the SIRA service loaded its state:
curl -s http://127.0.0.1:8040/healthz | python3 -m json.tool
# Want: "ok": true, "corpus_size": NN_THOUSAND, "query_prompt_loaded": true,
#       "rerank_prompt_loaded": true.

# Terminal 3 — NORA web app
# By default it points at http://127.0.0.1:8040 for the SIRA service.
# Override with NORA_SIRA_QUERY_URL=... if you run the service elsewhere.
python -m core.src.web.app   # or however you normally start NORA's web
```

Open `http://<host>:<port>/test`, click the **SIRA Retrieval** tab, type a query. The response is a ranked list of req_ids with bm25 + rerank scores, NO synthesized answer. Interactive latency is dominated by the LLM rerank step — at `concurrency=1` + a slow proprietary endpoint, expect **~30 seconds to ~12 minutes per query** depending on `NORA_SIRA_RERANK_TOP_N`.

**Tuning the latency:**

| Setting | Default | Tradeoff |
|---|---|---|
| `NORA_SIRA_RERANK_TOP_N` | 20 | Smaller = faster (fewer LLM rerank calls) but loses any correct doc not in the BM25-with-expansion top-N |
| `NORA_SIRA_TOP_K` | 10 | UI cap; doesn't affect latency |

For a quick first-look at SIRA's retrieval shape, drop `NORA_SIRA_RERANK_TOP_N=10` — interactive latency drops to ~6 min on a 36s/call endpoint.

## Network access — what gets downloaded

If your work PC blocks HF or has restricted outbound HTTPS, here's the exhaustive list of what SIRA reaches for:

### Install-time (one-time, on whichever box you install)

| Source | What | Bypass |
|---|---|---|
| `download.pytorch.org/whl/cu130/` | torch, torchvision | Pre-download wheels on a connected box: `uv pip download torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu130 -d wheels/`. Transfer `wheels/` over. Install with `uv pip install --no-index --find-links wheels/ torch torchvision`. |
| `docs.sglang.ai/whl/cu130/` | sglang-kernel | Same pattern. |
| `flashinfer.ai/whl/cu130/` | flashinfer-jit-cache | Same pattern. |
| PyPI (`pypi.org`) | Everything else (~30 deps incl. fastapi, hydra-core, datasets, beir, tantivy, transformers, etc.) | Mirror via local PyPI proxy / pre-download. |
| `crates.io` (Rust toolchain registry) | bm25x crate deps | Run `cargo fetch` on a connected box; copy `~/.cargo/registry/` to the air-gapped box. Or rely on the lockfile that ships in the repo (`Cargo.lock` is committed). |

### Runtime with `data=nora` configuration

**Nothing.** Confirmed by grepping the whole repo:
- `huggingface_hub.snapshot_download` — only call site is `prepare_mteb_data.py`, gated by the `metadata.json`-exists check our adapter satisfies.
- No `nltk.download(...)` anywhere.
- BM25 tokenizer (`unicode_stem`) is Rust-internal via `unicode-normalization` + `rust-stemmers` crates — built in at compile time, no runtime download.
- sglang doesn't run — our shim is already listening on `sglang.port` (it responds to `/v1/models` with 200), so SIRA auto-detects it and doesn't try to spawn its own sub-process. All LLM call sites go through our shim → proprietary endpoint (`127.0.0.1` → company internal — no public network).

### Runtime if the shim ISN'T running when you start run_pipeline.py

SIRA's auto-detection probe (`GET /v1/models`) fails → it tries to spawn sglang locally, which `from_pretrained`'s the configured model (default `qwen3.6-35b-a3b-fp8:h100` per `scripts/configs/sglang/`). **That triggers an HF cache download for the model weights** — many gigabytes. Always start the shim FIRST. If the shim crashes mid-pipeline, SIRA's subsequent retries will also fail (its `_start_server` waits 900s by default before giving up); restart the shim and retry the pipeline rather than letting it fall through to sglang spawn.

### Defensive belt-and-suspenders

Set these env vars in any shell that runs SIRA on the work PC. They force all HF-aware libraries (`transformers`, `datasets`, `huggingface_hub`) to use only what's already in the local cache and fail loudly if they try to fetch:

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
```

Add these to `sandbox/sira/sandbox.sh` if you want them auto-set on `source`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `curl /healthz` returns "Connection refused" | Shim isn't running | `uvicorn sandbox.shim.openai_shim:app --port 8030` from repo root |
| `/v1/chat/completions` returns 501 with "NotImplementedError" | Adapter mode + stub `proprietary_provider.complete()` | Either implement `complete()` (step 5b) or switch to pass-through by setting `NORA_LLM_BASE_URL` (step 5a) and restarting the shim |
| `/v1/chat/completions` returns 502 with "upstream error: ..." | Pass-through mode + unreachable upstream (DNS, refused, timeout) | Check `NORA_LLM_BASE_URL` value; `curl -i $NORA_LLM_BASE_URL/chat/completions` independently to isolate |
| `/v1/chat/completions` returns 502 with "Server disconnected without sending a response" | Two distinct possible causes — diagnose by independently running the same request via `curl` against `$NORA_LLM_BASE_URL/chat/completions`. (a) **TLS verification fails** if `curl` ALSO fails the same way → set `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt` (or wherever your system stores the corporate-CA-aware bundle). Escape hatch: `NORA_LLM_VERIFY_SSL=false` (internal-only). (b) **Corporate HTTPS proxy interception** if `curl` succeeds (200) but the shim fails → `httpx` is going through `HTTPS_PROXY` while `curl` is bypassing it. Add the LLM hostname to `NO_PROXY` (so both tools bypass), or set `NORA_LLM_SKIP_PROXY=true` on the shim. `curl /healthz` should then show `"skip_proxy": true`. |
| Pass-through returns 401 / 403 from upstream | Bad / missing `NORA_LLM_API_KEY` | Confirm key value and that the upstream accepts it via direct curl |
| Pass-through returns 400 "model not found" from upstream | SIRA's `model` field (e.g. `qwen3.6-35b-a3b-fp8:h100`) isn't recognized by your endpoint | Set `NORA_LLM_MODEL` to the actual model name and restart the shim |
| `prepare` stage tries to download from HF anyway | `metadata.json` missing or unreadable | `ls sandbox/adapter/out/nora/raw/metadata.json`; re-run adapter |
| `bm25` stage error "No module named 'bm25x'" | Maturin build didn't install | `cd sandbox/sira/src/sira/bm25x/python && maturin develop --release` |
| `enrich_corpus` extremely slow / endpoint times out / 5xx errors | At default `concurrency=1` (set in our nora.yaml for proxy-throttled environments), serial is the floor — slowness is the proprietary endpoint's per-call latency, not parallelism. If your environment ISN'T proxy-throttled, override up on CLI: `enrich.concurrency=8` (or higher) |
| `rerank` extremely slow | top_n=200 × N queries × 1 LLM call each adds up | Override `rerank.top_n=50` first, then dial up |
| sglang process keeps trying to start | The shim isn't responding on `sglang.port`, so SIRA falls through to spawning its own server | Start the shim BEFORE launching `run_pipeline.py`. Confirm with `curl -s http://127.0.0.1:8030/v1/models` — must return 200 with a model list |
| `hydra.errors.ConfigCompositionException: Could not override 'server.auto_start'` | Stale instruction — the flag doesn't exist in SIRA's config | Drop the `server.auto_start=false` argument entirely; detection is automatic (see "Critical flags" note above) |
| `hydra.errors.ConfigCompositionException: Could not override 'enrich.concurrency'` (or `rerank.top_n`, etc.) | The selected config (`enrich=nora` / `rerank=nora`) doesn't extend `default.yaml`, so the field doesn't exist in the merged config | Our YAMLs must declare `defaults: [default, _self_]` at the top — fixed in commit 47c5e3a (or later). After `git pull`, **re-run `bash sandbox/install_configs.sh`** to copy the updated YAMLs into the SIRA clone. As a one-shot workaround on the CLI: `+enrich.concurrency=8` (the `+` prefix appends rather than overrides) |
| `RuntimeError: sglang server process died during startup` (shim is up + reachable via curl) | SIRA's auto-detect probe (`urllib.request.urlopen('http://127.0.0.1:{port}/v1/models')`) is going through `HTTP_PROXY`. urllib honors NO_PROXY but doesn't auto-bypass localhost like curl does. The probe times out, SIRA falls through to spawning sglang locally, sglang can't start (no GPU stack on the trimmed install) → that error. | `source sandbox/activate.sh` (which now auto-adds `127.0.0.1,localhost,::1` to NO_PROXY since fix-commit), OR strip proxy vars from the pipeline terminal: `env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy python scripts/run_pipeline.py …`. Confirm with the SIRA log line: should see `Using existing LLM server on port 8030` (not `Starting sglang server...`). |
| eval numbers look wrong (e.g. 0% recall) | Adapter wrote `_id` field that doesn't match qrels `corpus-id` | Spot-check: `head -1 corpus.jsonl` and one qrel row — `_id` must equal `corpus-id` |
| Adapter skips most reqs as "no-id" | Source `_tree.json` has empty `req_id` fields | Re-run NORA parse stage; if the source corpus genuinely lacks req_ids, this strand's approach doesn't apply |
| `Illegal instruction (core dumped)` + polars warning about "avx2, fma, bmi1, bmi2, lzcnt, movbe" | CPU lacks AVX2 (older / virtualized x86_64) and you installed plain `polars` | `uv pip install --reinstall --system-certs 'polars[rtcompat]'`. Alternative spelling if the extra doesn't resolve: `uv pip install --system-certs polars-lts-cpu` (after `uv pip uninstall polars`). |
