#!/usr/bin/env bash
# Activate the SIRA sandbox under NORA's uv-based install.
# Source this from the NORA repo root:
#
#   source sandbox/activate.sh
#
# Replacement for upstream `sandbox/sira/sandbox.sh`, which is conda-only
# (`conda activate sira312`). Our SETUP.md step 2a uses `uv venv` so the
# conda env doesn't exist — this script does the equivalent for uv:
#   * activates sandbox/sira/.venv
#   * adds sandbox/sira/ to PYTHONPATH so `import sira` resolves
#   * sets the HF "offline" env vars (defensive — runtime never hits HF
#     for `data=nora` per our audit, but this fails loudly if anything
#     drifts)
#
# Intentionally does NOT set the GPU-tuning env vars upstream sandbox.sh
# does (NCCL_DEBUG, FLASHINFER_*, TORCH_NCCL_ASYNC_ERROR_HANDLING, etc.) —
# we're bypassing sglang entirely via the FastAPI shim.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIRA_DIR="$REPO_ROOT/sandbox/sira"
VENV="$SIRA_DIR/.venv"

if [ ! -d "$VENV" ]; then
    echo "ERROR: $VENV not found — run SETUP.md step 2a first:" >&2
    echo "  cd $SIRA_DIR && uv venv .venv --python 3.12" >&2
    return 1 2>/dev/null || exit 1
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
export PYTHONPATH="$SIRA_DIR:${PYTHONPATH:-}"

# Defensive belt-and-suspenders. With `data=nora` our pipeline never
# reaches HuggingFace at runtime — but unset env vars + a stale import
# could change that silently. These force any HF-aware library
# (transformers, datasets, huggingface_hub) to use only the local cache
# and fail loudly if it tries to fetch.
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export HF_DATASETS_OFFLINE="${HF_DATASETS_OFFLINE:-1}"

# bm25x is built once at install time (SETUP.md step 3). If the source
# changes (rare on our trimmed-install path), rebuild manually:
#   cd sandbox/sira/src/sira/bm25x/python && maturin develop --release
# Unlike upstream sandbox.sh we don't auto-rebuild — keeps `source` fast.

echo "SIRA sandbox active (venv=$VENV)"
