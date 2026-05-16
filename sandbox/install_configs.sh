#!/usr/bin/env bash
# Install the NORA-specific SIRA hydra configs + prompts into the
# cloned upstream SIRA repo. The clone (`sandbox/sira/`) is gitignored,
# so we don't commit anything inside it — this script copies our
# committed configs in on demand.
#
# Run from the repo root (after `git clone … sandbox/sira` succeeded):
#
#   bash sandbox/install_configs.sh
#
# Idempotent — copies overwrite. Re-run after editing any of:
#   sandbox/sira_configs/{data,enrich,rerank}/nora.yaml
#   sandbox/prompts/{doc,query,relevance}_requirement_v*.txt

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SIRA_CLONE="$REPO_ROOT/sandbox/sira"

if [ ! -d "$SIRA_CLONE" ]; then
    echo "error: $SIRA_CLONE not found — run 'git clone --depth 1 https://github.com/facebookresearch/sira.git sandbox/sira' first" >&2
    exit 1
fi

set -x

# Hydra configs — data, enrich, rerank.
cp "$REPO_ROOT/sandbox/sira_configs/data/nora.yaml"   "$SIRA_CLONE/scripts/configs/data/nora.yaml"
cp "$REPO_ROOT/sandbox/sira_configs/enrich/nora.yaml" "$SIRA_CLONE/scripts/configs/enrich/nora.yaml"
cp "$REPO_ROOT/sandbox/sira_configs/rerank/nora.yaml" "$SIRA_CLONE/scripts/configs/rerank/nora.yaml"

# Telecom-tuned prompts referenced by the enrich/rerank configs above.
cp "$REPO_ROOT/sandbox/prompts/doc_requirement_v01.txt"       "$SIRA_CLONE/scripts/configs/enrich/prompts/doc_requirement_v01.txt"
cp "$REPO_ROOT/sandbox/prompts/query_requirement_v01.txt"     "$SIRA_CLONE/scripts/configs/enrich/prompts/query_requirement_v01.txt"
cp "$REPO_ROOT/sandbox/prompts/relevance_requirement_v01.txt" "$SIRA_CLONE/scripts/configs/rerank/prompts/relevance_requirement_v01.txt"

set +x
echo
echo "OK — installed 3 hydra configs + 3 prompts into $SIRA_CLONE/scripts/configs/"
