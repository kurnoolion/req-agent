# Manual Install: gemma3:12b for Ollama

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

| # | Description    | Size     | URL |
|---|----------------|----------|-----|
| 1 | Model weights  | **8.1 GB** | `https://registry.ollama.ai/v2/library/gemma3/blobs/sha256:e8ad13eff07a78d89926e9e8b882317d082ef5bf9768ad7b50fcdbbcd63748de` |
| 2 | Config         | 490 B    | `https://registry.ollama.ai/v2/library/gemma3/blobs/sha256:6819964c2bcf53f6dd3593f9571e91cbf2bab9665493f870f96eeb29873049b4` |
| 3 | Template       | 358 B    | `https://registry.ollama.ai/v2/library/gemma3/blobs/sha256:e0a42594d802e5d31cdc786deb4823edb8adff66094d49de8fffe976d753e348` |
| 4 | License        | 8 KB     | `https://registry.ollama.ai/v2/library/gemma3/blobs/sha256:dd084c7d92a3c1c14cc09ae77153b903fd2024b64a100a0cc8ec9316063d2dbc` |
| 5 | Params         | 77 B     | `https://registry.ollama.ai/v2/library/gemma3/blobs/sha256:3116c52250752e00dd06b16382e952bd33c34fd79fc4fe3a5d2c77cf7de1b14b` |

Only file #1 (8.1 GB) will take time. The rest are tiny.

## Step 2: Create directory structure

```bash
mkdir -p ~/.ollama/models/manifests/registry.ollama.ai/library/gemma3
mkdir -p ~/.ollama/models/blobs
```

## Step 3: Write the manifest file

```bash
cat > ~/.ollama/models/manifests/registry.ollama.ai/library/gemma3/12b << 'EOF'
{"schemaVersion":2,"mediaType":"application/vnd.docker.distribution.manifest.v2+json","config":{"mediaType":"application/vnd.docker.container.image.v1+json","digest":"sha256:6819964c2bcf53f6dd3593f9571e91cbf2bab9665493f870f96eeb29873049b4","size":490},"layers":[{"mediaType":"application/vnd.ollama.image.model","digest":"sha256:e8ad13eff07a78d89926e9e8b882317d082ef5bf9768ad7b50fcdbbcd63748de","size":8149180896},{"mediaType":"application/vnd.ollama.image.template","digest":"sha256:e0a42594d802e5d31cdc786deb4823edb8adff66094d49de8fffe976d753e348","size":358},{"mediaType":"application/vnd.ollama.image.license","digest":"sha256:dd084c7d92a3c1c14cc09ae77153b903fd2024b64a100a0cc8ec9316063d2dbc","size":8432},{"mediaType":"application/vnd.ollama.image.params","digest":"sha256:3116c52250752e00dd06b16382e952bd33c34fd79fc4fe3a5d2c77cf7de1b14b","size":77}]}
EOF
```

## Step 4: Move downloaded files to blobs directory

Rename each downloaded file to its digest. Note: use `-` (dash) not `:` (colon) after `sha256`.

```bash
# File 1 — Model weights (8.1 GB)
mv <downloaded-file-1> ~/.ollama/models/blobs/sha256-e8ad13eff07a78d89926e9e8b882317d082ef5bf9768ad7b50fcdbbcd63748de

# File 2 — Config
mv <downloaded-file-2> ~/.ollama/models/blobs/sha256-6819964c2bcf53f6dd3593f9571e91cbf2bab9665493f870f96eeb29873049b4

# File 3 — Template
mv <downloaded-file-3> ~/.ollama/models/blobs/sha256-e0a42594d802e5d31cdc786deb4823edb8adff66094d49de8fffe976d753e348

# File 4 — License
mv <downloaded-file-4> ~/.ollama/models/blobs/sha256-dd084c7d92a3c1c14cc09ae77153b903fd2024b64a100a0cc8ec9316063d2dbc

# File 5 — Params
mv <downloaded-file-5> ~/.ollama/models/blobs/sha256-3116c52250752e00dd06b16382e952bd33c34fd79fc4fe3a5d2c77cf7de1b14b
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
# Should show: gemma3:12b

# Quick test
ollama run gemma3:12b "Hello, what model are you?"
```
