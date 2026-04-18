# Manual Install: gemma4:e4b for Ollama

For environments where `ollama pull` fails (e.g., corporate proxy, self-signed certificates).

## Step 0: Install Ollama with CUDA/GPU support

As of v0.21.0, CUDA libraries are bundled into the main package (no separate `-cuda` download).
The format is `.tar.zst` (not `.tgz`).

Download in your browser from GitHub releases:

| File | Size | URL |
|------|------|-----|
| Ollama (with CUDA) | **2 GB** | `https://github.com/ollama/ollama/releases/download/v0.21.0/ollama-linux-amd64.tar.zst` |

Then install:

```bash
# Install zstd if not already present
sudo apt install zstd -y

# Extract to /usr/local (contains bin/ollama + lib/ollama/cuda_v12/, cuda_v13/, etc.)
sudo tar --use-compress-program=unzstd -xf ollama-linux-amd64.tar.zst -C /usr/local

# Verify CUDA libs are in place
ls /usr/local/lib/ollama/cuda_v12/

# Start Ollama and verify GPU is detected
ollama serve &
nvidia-smi   # should show ollama process using GPU memory
```

## Step 1: Download these files in your browser

| # | Description    | Size       | URL |
|---|----------------|------------|-----|
| 1 | Model weights  | **9.6 GB** | `https://registry.ollama.ai/v2/library/gemma4/blobs/sha256:4c27e0f5b5adf02ac956c7322bd2ee7636fe3f45a8512c9aba5385242cb6e09a` |
| 2 | Config         | 473 B      | `https://registry.ollama.ai/v2/library/gemma4/blobs/sha256:f0988ff50a2458c598ff6b1b87b94d0f5c44d73061c2795391878b00b2285e11` |
| 3 | License        | 11 KB      | `https://registry.ollama.ai/v2/library/gemma4/blobs/sha256:7339fa418c9ad3e8e12e74ad0fd26a9cc4be8703f9c110728a992b193be85cb2` |
| 4 | Params         | 42 B       | `https://registry.ollama.ai/v2/library/gemma4/blobs/sha256:56380ca2ab89f1f68c283f4d50863c0bcab52ae3f1b9a88e4ab5617b176f71a3` |

Only file #1 (9.6 GB) will take time. The rest are tiny.

## Step 2: Create directory structure

```bash
mkdir -p ~/.ollama/models/manifests/registry.ollama.ai/library/gemma4
mkdir -p ~/.ollama/models/blobs
```

## Step 3: Write the manifest file

```bash
cat > ~/.ollama/models/manifests/registry.ollama.ai/library/gemma4/e4b << 'EOF'
{"schemaVersion":2,"mediaType":"application/vnd.docker.distribution.manifest.v2+json","config":{"mediaType":"application/vnd.docker.container.image.v1+json","digest":"sha256:f0988ff50a2458c598ff6b1b87b94d0f5c44d73061c2795391878b00b2285e11","size":473},"layers":[{"mediaType":"application/vnd.ollama.image.model","digest":"sha256:4c27e0f5b5adf02ac956c7322bd2ee7636fe3f45a8512c9aba5385242cb6e09a","size":9608338848},{"mediaType":"application/vnd.ollama.image.license","digest":"sha256:7339fa418c9ad3e8e12e74ad0fd26a9cc4be8703f9c110728a992b193be85cb2","size":11355},{"mediaType":"application/vnd.ollama.image.params","digest":"sha256:56380ca2ab89f1f68c283f4d50863c0bcab52ae3f1b9a88e4ab5617b176f71a3","size":42}]}
EOF
```

## Step 4: Move downloaded files to blobs directory

Rename each downloaded file to its digest. Note: use `-` (dash) not `:` (colon) after `sha256`.

```bash
# File 1 — Model weights (9.6 GB)
mv <downloaded-file-1> ~/.ollama/models/blobs/sha256-4c27e0f5b5adf02ac956c7322bd2ee7636fe3f45a8512c9aba5385242cb6e09a

# File 2 — Config
mv <downloaded-file-2> ~/.ollama/models/blobs/sha256-f0988ff50a2458c598ff6b1b87b94d0f5c44d73061c2795391878b00b2285e11

# File 3 — License
mv <downloaded-file-3> ~/.ollama/models/blobs/sha256-7339fa418c9ad3e8e12e74ad0fd26a9cc4be8703f9c110728a992b193be85cb2

# File 4 — Params
mv <downloaded-file-4> ~/.ollama/models/blobs/sha256-56380ca2ab89f1f68c283f4d50863c0bcab52ae3f1b9a88e4ab5617b176f71a3
```

Replace `<downloaded-file-N>` with the actual filenames your browser saved (often the digest hash or a generic name).

## Step 5: Restart Ollama and verify

```bash
# Restart Ollama
sudo systemctl restart ollama
# Or if running manually:
# ollama serve

# Verify the model is recognized
ollama list
# Should show: gemma4:e4b

# Quick test
ollama run gemma4:e4b "Hello, what model are you?"
```
