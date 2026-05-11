"""Ollama embedding provider for local model inference.

Uses Ollama's `/api/embeddings` endpoint. Same offline-friendly distribution
path as the existing Ollama LLM provider — once Ollama is set up, embedding
models are pulled with `ollama pull <model>` (no separate HuggingFace cache).

Recommended embedding models:
  - nomic-embed-text     (768d, ~270MB, balanced)
  - mxbai-embed-large    (1024d, ~670MB, top quality)
  - all-minilm           (384d, ~45MB, fastest)

Pull with: `ollama pull nomic-embed-text`

Satisfies the EmbeddingProvider protocol — no inheritance.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:11434"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


def _build_opener(base_url: str) -> urllib.request.OpenerDirector:
    """Build a urllib opener that bypasses HTTP_PROXY for loopback URLs.

    Without this, HTTP_PROXY / http_proxy env vars (common on corporate
    work laptops) cause urllib to route http://localhost:11434 through the
    proxy → connection times out. curl ignores *_proxy for localhost by
    default; urllib does not.
    """
    host = (urlsplit(base_url).hostname or "").lower()
    if host in _LOOPBACK_HOSTS:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = sum(x * x for x in vec) ** 0.5
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


_DEFAULT_MAX_INPUT_CHARS = 8000

# Per-chunk shrink-retry policy for 5xx responses. AT-command tables and
# other dense corpora occasionally trip the embedding model's token
# budget even at the char-truncation cap; halving the text twice rescues
# nearly all of them. After exhausted retries, ``ChunkEmbeddingError``
# is raised so the builder can skip the chunk rather than fail the
# whole stage.
_MAX_SHRINK_RETRIES = 2
_MIN_SHRINK_CHARS = 500


class ChunkEmbeddingError(RuntimeError):
    """A single chunk failed to embed after retry-with-shrink.

    The builder catches this and skips the chunk while continuing the
    rest of the batch. Other ``RuntimeError`` subclasses (e.g. wire-
    level URLError) still abort the whole stage.
    """

    def __init__(
        self,
        idx: int,
        text_preview: str,
        attempts: int,
        last_error: Exception,
    ) -> None:
        self.idx = idx
        self.text_preview = text_preview
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"chunk {idx} embedding failed after {attempts} attempt(s); "
            f"preview={text_preview!r}; last_error={last_error}"
        )
"""Conservative default cap on per-text input length sent to /api/embeddings.

Different Ollama embedding models have different effective context windows.
Empirical limits observed:
  - nomic-embed-text     → ~32K chars before 500
  - qwen3-embedding-q8-0:4b → 500s above ~16K chars
At 8K we're comfortably under both. Tunable via `OllamaEmbedder(max_input_chars=...)`
or `VectorStoreConfig.extra["ollama_max_input_chars"]`. Texts longer than this
are truncated (with a warning) rather than dropped, since dropping a chunk
breaks the chunk-id ↔ vector correspondence the store relies on.
"""


class OllamaEmbedder:
    """Embedding provider using Ollama's /api/embeddings endpoint.

    Satisfies the EmbeddingProvider protocol.

    Args:
        model_name: Ollama embedding model (e.g., "nomic-embed-text").
        base_url: Ollama server URL.
        timeout: Per-request timeout in seconds.
        normalize: L2-normalize embeddings before returning.
        max_input_chars: Truncate inputs longer than this before embedding.
            Defaults to a conservative value that fits any common Ollama
            embedding model; raise if you know your model handles more.
    """

    def __init__(
        self,
        model_name: str = "nomic-embed-text",
        base_url: str = _DEFAULT_BASE_URL,
        timeout: int = 60,
        normalize: bool = True,
        max_input_chars: int = _DEFAULT_MAX_INPUT_CHARS,
    ) -> None:
        self._model_name = model_name
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._normalize = normalize
        self._max_input_chars = max_input_chars
        self._opener = _build_opener(self._base_url)
        self._dimension: int | None = None
        self._truncated_count = 0

        # Verify reachability + check that the model is pulled. Match
        # OllamaProvider's __init__ behavior: warn (don't fail) if the model
        # isn't listed yet, since `ollama pull` may be in progress.
        try:
            req = urllib.request.Request(f"{self._base_url}/api/tags")
            with self._opener.open(req, timeout=5) as resp:
                data = json.loads(resp.read())
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Cannot connect to Ollama at {self._base_url}. "
                f"Is Ollama running? (ollama serve)\n"
                f"Error: {e}"
            ) from e

        models = [m.get("name", "") for m in data.get("models", [])]
        # Allow exact match or "name:tag" prefix
        present = model_name in models or any(
            m.startswith(f"{model_name}:") for m in models
        )
        if not present:
            available = ", ".join(models) if models else "none"
            logger.warning(
                f"Embedding model '{model_name}' not found on Ollama server. "
                f"Available: {available}. Pull with: ollama pull {model_name}"
            )
        else:
            logger.info(
                f"OllamaEmbedder ready: model={model_name}, server={self._base_url}, "
                f"normalize={normalize}"
            )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts.

        Ollama's /api/embeddings is single-text per call; we loop. For large
        batches this is slower than sentence-transformers' native batching,
        but it keeps the wire protocol simple and matches what `ollama pull`
        ships out of the box.

        **Per-text resilience**: HTTP 5xx responses (typically token-count
        overruns or backend OOM on dense content like AT-command tables)
        trigger a retry with the text halved, up to ``_MAX_SHRINK_RETRIES``
        times. Non-HTTP errors (connection refused, timeout) propagate
        immediately since they indicate a server-level problem the caller
        should handle. After exhausted retries on a 5xx, a
        ``ChunkEmbeddingError`` is raised so the builder can skip just
        that chunk instead of failing the entire stage.
        """
        if not texts:
            return []
        vectors: list[list[float]] = []
        for i, text in enumerate(texts):
            vec = self._embed_one_with_retry(text, i)
            vectors.append(vec)
            if self._dimension is None:
                self._dimension = len(vec)
        return vectors

    def _embed_one_with_retry(self, text: str, idx: int) -> list[float]:
        """Embed a single text; retry with halved length on 5xx."""
        if len(text) > self._max_input_chars:
            logger.warning(
                f"Text {idx} length {len(text)} > max_input_chars "
                f"{self._max_input_chars}; truncating "
                f"({len(text) - self._max_input_chars} chars dropped)"
            )
            text = text[:self._max_input_chars]
            self._truncated_count += 1

        attempt = 0
        current = text
        last_error: Exception | None = None
        while True:
            try:
                return self._embed_one(current, idx)
            except urllib.error.HTTPError as e:
                last_error = e
                # 5xx → server-side failure; try shrinking. 4xx → caller-
                # side problem (bad model name, malformed request); raise
                # immediately.
                if not (500 <= e.code < 600):
                    raise
                if attempt >= _MAX_SHRINK_RETRIES or len(current) <= _MIN_SHRINK_CHARS:
                    raise ChunkEmbeddingError(
                        idx=idx,
                        text_preview=text[:80],
                        attempts=attempt + 1,
                        last_error=e,
                    ) from e
                new_len = max(_MIN_SHRINK_CHARS, len(current) // 2)
                logger.warning(
                    "Ollama 5xx on chunk %d (len=%d); retry %d/%d with len=%d",
                    idx, len(current), attempt + 1, _MAX_SHRINK_RETRIES, new_len,
                )
                current = current[:new_len]
                attempt += 1
            except urllib.error.URLError as e:
                # Non-HTTP (DNS, refused, timeout) — propagate as before.
                raise RuntimeError(
                    f"Ollama embedding request failed (text {idx}, "
                    f"length={len(current)} chars, "
                    f"preview={current[:80]!r}{'…' if len(current) > 80 else ''}): {e}"
                ) from e

    def _embed_one(self, text: str, idx: int) -> list[float]:
        """One POST to /api/embeddings; raises URLError / HTTPError on failure."""
        payload = json.dumps(
            {"model": self._model_name, "prompt": text}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self._opener.open(req, timeout=self._timeout) as resp:
            data = json.loads(resp.read())
        vec = data.get("embedding", [])
        if not vec:
            raise RuntimeError(
                f"Ollama returned empty embedding for input #{idx}; "
                f"check that '{self._model_name}' is an embedding model "
                f"(LLM models like gemma3:12b don't expose /api/embeddings output)"
            )
        if self._normalize:
            vec = _l2_normalize(vec)
        return vec

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query.

        Ollama's /api/embeddings does not differentiate query vs document
        encoding, so this just delegates to embed().
        """
        return self.embed([text])[0]

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            # Probe with a short non-empty string to discover dimensionality.
            # Empty strings are rejected by some embedding models (Qwen3 family
            # returns {"embedding":[]} for ""); use a single ASCII character.
            self.embed(["a"])
        return self._dimension or 0

    @property
    def model_name(self) -> str:
        return self._model_name
