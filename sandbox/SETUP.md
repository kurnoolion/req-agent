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

# Step 1: only the deps the four stages need.
uv pip install --system-certs \
    aiohttp hydra-core omegaconf polars maturin pybind11 huggingface_hub

# Step 2: install sira itself in editable mode, skipping its dep tree
# entirely. --no-deps means uv won't try to fetch torch / sglang / etc.
uv pip install --system-certs --no-deps -e .

source sandbox.sh   # sets PYTHONPATH + cd helpers
```

This avoids all three custom wheel indexes (`download.pytorch.org`, `docs.sglang.ai`, `flashinfer.ai`) — handy if your corporate firewall whitelists only PyPI.

#### 2b. Full install — once you have GPU + open network (e.g. DGX Spark)

```bash
cd sandbox/sira
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e .
source sandbox.sh
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

### 5. Implement `proprietary_provider.complete()`

Open `customizations/llm/proprietary_provider.py` and replace the `complete()` body with the call to your company's LLM endpoint. The signature must continue to match the `LLMProvider` Protocol:

```python
def complete(self, prompt: str, system: str = "",
             temperature: float = 0.0, max_tokens: int = 4096) -> str
```

Return the completion text. See `customizations/llm/README.md` for guidance.

## Verify install

### A. Shim health

In one terminal, from `$REPO_ROOT`:

```bash
uvicorn sandbox.shim.openai_shim:app --port 8030
```

In another:

```bash
curl -s http://127.0.0.1:8030/healthz
# {"ok": true, "model": "...", "endpoint": "...", "calls": 0}

curl -s -X POST http://127.0.0.1:8030/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "test", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 16}'
```

If `complete()` is implemented: 200 with an `OpenAI-shaped` response.
If `complete()` is the stub: 501 with `"NotImplementedError..."` — implement step 5 first.

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

From `sandbox/sira/`:

```bash
source .venv/bin/activate
source sandbox.sh
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
cd $REPO_ROOT/sandbox/sira
source .venv/bin/activate && source sandbox.sh
python scripts/run_pipeline.py \
    data=nora \
    enrich=nora \
    rerank=nora \
    db_root=$(realpath ../adapter/out) \
    sglang.port=8030 \
    server.auto_start=false \
    enrich.concurrency=8 \
    rerank.concurrency=8
```

Critical flags:
- `server.auto_start=false` — SIRA does **not** spawn its own sglang process; talks to our shim instead.
- `sglang.port=8030` — SIRA's hardcoded `http://127.0.0.1:{port}/v1/chat/completions` resolves to our shim.
- `enrich.concurrency=8` / `rerank.concurrency=8` — defaults are 4096 / 2048 (calibrated for a local H100 sglang). At those numbers, our shim → proprietary endpoint will saturate. Tune to whatever the proprietary endpoint absorbs cleanly.

Output: per-stage eval JSONs at `sandbox/adapter/out/nora/eval/{baseline, doc-enrich, query-enrich, rerank}/best.json`. Compare `recall@10` across stages — that's the per-stage lift attributable to corpus enrichment / query enrichment / LLM reranking. Compare the final `recall@10` against NORA's A4 baseline (88.0% overall / 67.6% accuracy on the same 18-Q set).

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
- sglang doesn't run — `server.auto_start=false` keeps SIRA from spawning its sub-process. The only LLM call site goes through our shim → proprietary endpoint (`127.0.0.1` → company internal — no public network).

### Runtime if you flip `server.auto_start=true`

SIRA would spawn sglang locally, which `from_pretrained`'s the configured model (default `qwen3.6-35b-a3b-fp8:h100` per `scripts/configs/sglang/`). **That triggers an HF cache download for the model weights** — many gigabytes. Do not flip this until your work PC can either reach HF or you've pre-staged the model in `$HF_HOME`.

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
| `/v1/chat/completions` returns 501 with "NotImplementedError" | `proprietary_provider.complete()` is still the stub | Implement the body per `customizations/llm/README.md` |
| `prepare` stage tries to download from HF anyway | `metadata.json` missing or unreadable | `ls sandbox/adapter/out/nora/raw/metadata.json`; re-run adapter |
| `bm25` stage error "No module named 'bm25x'" | Maturin build didn't install | `cd sandbox/sira/src/sira/bm25x/python && maturin develop --release` |
| `enrich_corpus` extremely slow / endpoint times out | Default `concurrency=4096` saturates the proprietary endpoint | Override on CLI: `enrich.concurrency=4` (or whatever your endpoint absorbs) |
| `rerank` extremely slow | top_n=200 × N queries × 1 LLM call each adds up | Override `rerank.top_n=50` first, then dial up |
| sglang process keeps trying to start | `server.auto_start` defaulting to true | Pass `server.auto_start=false` on every `run_pipeline.py` invocation |
| eval numbers look wrong (e.g. 0% recall) | Adapter wrote `_id` field that doesn't match qrels `corpus-id` | Spot-check: `head -1 corpus.jsonl` and one qrel row — `_id` must equal `corpus-id` |
| Adapter skips most reqs as "no-id" | Source `_tree.json` has empty `req_id` fields | Re-run NORA parse stage; if the source corpus genuinely lacks req_ids, this strand's approach doesn't apply |
