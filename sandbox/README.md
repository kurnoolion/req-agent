# sandbox/

Scratch area for the `sira` strand (and similar future experiments).
**Not under `core/src/`** — the curated NORA module surface stays
unchanged by what lives here. Built artifacts and cloned upstream
repos are gitignored; only the glue code we write is committed.

> **Want to run SIRA?** See [`SETUP.md`](SETUP.md) for the step-by-step
> install + verify procedure (prereqs, clone, env, configs, smoke
> tests, troubleshooting). This README is the layout reference + Phase 0
> findings.

## Layout

| Path | What | Versioned |
|---|---|---|
| `sira/` | Cloned `facebookresearch/sira` (`--depth 1`). Pull fresh with `git -C sandbox/sira pull` to track upstream. | ❌ gitignored |
| `shim/openai_shim.py` | FastAPI service that exposes `/v1/chat/completions` and routes onto `customizations/llm/proprietary_provider.py`. Run with `uvicorn`. SIRA talks to this instead of a local sglang. | ✅ |
| `adapter/nora_to_beir.py` | Converts NORA parse output (`<env_dir>/out/parse/*_tree.json`) + the 18-Q eval set into BEIR-format `corpus.jsonl` + `queries.jsonl` + `qrels/test.tsv`. | ✅ |
| `prompts/doc_requirement_v01.txt` | Telecom-tuned doc-enrichment prompt (replaces SIRA's Wikipedia-tuned `doc_v07.txt`). | ✅ |
| `prompts/query_requirement_v01.txt` | Mirror query-enrichment prompt. | ✅ |
| `prompts/relevance_requirement_v01.txt` | LLM-reranker prompt. | ✅ |
| `sira_configs/data/nora.yaml` | SIRA hydra dataset config — `name=nora`, no HF fetch (adapter writes `metadata.json`, prepare-stage skips download). | ✅ |
| `sira_configs/enrich/nora.yaml` | Enrichment overrides — references `doc_requirement_v01.txt` / `query_requirement_v01.txt`. | ✅ |
| `sira_configs/rerank/nora.yaml` | Reranker overrides — references `relevance_requirement_v01.txt`. | ✅ |
| `install_configs.sh` | One-command installer that copies the 3 hydra configs + 3 prompts into the (gitignored) `sira/` clone's `scripts/configs/` tree. Idempotent. Re-run after editing any of those source files. | ✅ |

## Phase 0 findings (2026-05-16)

1. **LLM call shape**: SIRA hits `http://127.0.0.1:{port}/v1/chat/completions` with a standard OpenAI Chat Completions payload (`model`, `messages`, `max_tokens`, `temperature`, optional `seed` / `chat_template_kwargs`). No sglang-specific schema-constrained generation. → The shim above routes directly with zero translation; **no SIRA fork needed**.
2. **Generic prompts are Wikipedia-tuned**: `doc_v07.txt` examples are "Nicole Gale Anderson", "Tyrion 'The Imp'", "ice giant planet". `query_v07.txt` examples are "FIFA, football, host nation" for a World Cup query. `relevance_v04.txt` examples are "the Neptune Wikipedia article". Direct application to MNO device requirements would produce poor enrichment. → Telecom variants drafted as `v01`; iterate against real corpus output.
3. **Dependency stack is GPU-pinned**: `torch==2.9.1` + CUDA-13 indexes, `sglang==0.5.10.post1`, `flash-attn-4[cu13]`, `flashinfer-jit-cache`. Won't install on the no-GPU dev PC. **The scifact smoke run is blocked on a GPU env** (work laptop RTX A4600 or DGX Spark when up).
4. `bm25x` Rust crate has CPU mode (`default = []`, `cuda = ["dep:cudarc"]`), but the top-level `pyproject.toml`'s torch / sglang pins force a GPU install via `pip install -e .`.

## Phase 0 status

Done on dev PC (no GPU required):
- ✅ Repo cloned + inspected
- ✅ Generic prompts read; telecom variants drafted (`v01`)
- ✅ FastAPI shim built; smoke-tested with the stub provider (returns 501 as expected)
- ✅ Adapter built; smoke-tested with a synthetic `_tree.json`. Emits SIRA-internal `raw/` layout (corpus.jsonl, queries-test.jsonl, qrels-test.jsonl, metadata.json) so `prepare_mteb_data.py` early-returns and no HF download is triggered
- ✅ Three hydra configs (`data/nora.yaml`, `enrich/nora.yaml`, `rerank/nora.yaml`) + `install_configs.sh` to copy them + the prompts into the gitignored SIRA clone

Blocked until GPU env:
- ⏸ Run SIRA's `scifact` example end-to-end against the shim (to validate the shim under SIRA's actual request volume + the LLM-pipeline's enrichment behavior)
- ⏸ Run SIRA against the NORA-converted corpus (Phase 1 proper)

## Running

**Step 1 — Shim** (in one terminal at the repo root):

    uvicorn sandbox.shim.openai_shim:app --port 8030

(The shim wraps `customizations/llm/proprietary_provider.py`. Make sure
its `complete()` body is filled in for your deployment before SIRA hits
it under real load — the stub raises `NotImplementedError` → 501.)

**Step 2 — Adapter** (writes the SIRA-internal `raw/` layout):

    python -m sandbox.adapter.nora_to_beir \
        --env-dir /path/to/env_dir \
        --output sandbox/adapter/out/nora

**Step 3 — Install configs into the SIRA clone**:

    bash sandbox/install_configs.sh

**Step 4 — Run SIRA against NORA** (when GPU is online; assumes
SIRA's env is set up per its own README):

    cd $REPO_ROOT
    source sandbox/activate.sh
    cd sandbox/sira
    python scripts/run_pipeline.py \
        data=nora \
        enrich=nora \
        rerank=nora \
        db_root=$(realpath ../adapter/out) \
        sglang.port=8030

SIRA auto-detects an existing server on `sglang.port` via `GET /v1/models`
— our shim implements that endpoint, so as long as the shim is running
(see Step 1 above) SIRA picks it up automatically. If `/v1/models` 404s
or the port is unreachable, SIRA falls back to spawning sglang locally
(needs GPU + full install). See `SETUP.md` for the full procedure.
