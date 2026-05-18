"""Local shim that accepts SIRA's hardcoded
`http://127.0.0.1:{port}/v1/chat/completions` requests and routes them
onto your proprietary LLM. Two modes, selected by env vars:

  * **Pass-through mode** (recommended when the proprietary LLM already
    exposes an OpenAI-compatible Chat Completions endpoint). Set
    ``NORA_LLM_BASE_URL`` (and optionally ``NORA_LLM_API_KEY`` /
    ``NORA_LLM_MODEL``) and the shim forwards the request body verbatim
    upstream. `proprietary_provider.complete()` is NOT used; you don't
    need to implement it for this path to work.

  * **Adapter mode** (fallback for non-OpenAI providers). With
    ``NORA_LLM_BASE_URL`` unset, the shim collapses SIRA's messages
    into a (system, prompt) pair, calls
    ``customizations.llm.proprietary_provider.ProprietaryLLMProvider.complete()``,
    and re-envelopes the string response into the OpenAI shape SIRA
    expects.

SIRA's payload shape (OpenAI Chat Completions: `model`, `messages`,
`max_tokens`, `temperature`, optional `seed` / `chat_template_kwargs`)
is unchanged either way — only the upstream destination differs.

Run from the repo root:

    uvicorn sandbox.shim.openai_shim:app --port 8030

Then in SIRA's hydra config, set `sglang.port=8030` and SIRA will
transparently route every enrichment / reranking call here.

The shim is sandbox-only — never imported by NORA's `core/` modules.
"""

from __future__ import annotations

import os
import time
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict


# Pass-through mode wins when NORA_LLM_BASE_URL is set. The shim then
# forwards SIRA's request body verbatim (with optional `model` override
# and bearer-token injection) and returns the upstream response.
_LLM_BASE_URL = os.getenv("NORA_LLM_BASE_URL", "").rstrip("/")
_LLM_API_KEY = os.getenv("NORA_LLM_API_KEY", "")
_LLM_MODEL = os.getenv("NORA_LLM_MODEL", "")
_LLM_TIMEOUT = float(os.getenv("NORA_LLM_TIMEOUT", "300"))


# Adapter-mode provider is loaded lazily — only when pass-through is
# disabled. Keeps the shim usable without filling in proprietary_provider
# when the proprietary LLM speaks OpenAI directly.
def _load_provider():
    from customizations.llm.proprietary_provider import ProprietaryLLMProvider
    return ProprietaryLLMProvider(
        model=os.getenv("NORA_PROPRIETARY_MODEL", ""),
        endpoint=os.getenv("NORA_PROPRIETARY_ENDPOINT", ""),
    )


_provider = None if _LLM_BASE_URL else _load_provider()


app = FastAPI(title="NORA LLM shim for SIRA")


class _Message(BaseModel):
    role: str
    content: str


class _ChatRequest(BaseModel):
    # SIRA may pass extra fields (chat_template_kwargs, seed, top_p, ...).
    # Allow them — we read what we use and ignore the rest.
    model_config = ConfigDict(extra="allow")

    model: str = ""
    messages: list[_Message]
    max_tokens: int = 4096
    temperature: float = 0.0


@app.post("/v1/chat/completions")
def chat_completions(req: _ChatRequest) -> dict:
    """Pass-through if NORA_LLM_BASE_URL is set; adapter otherwise.

    In pass-through mode the request body goes upstream verbatim except
    that ``model`` is overridden when ``NORA_LLM_MODEL`` is set (some
    OpenAI-compatible endpoints reject unrecognized model strings — and
    SIRA may send a sglang-style identifier).

    In adapter mode SIRA's messages collapse into the (`system`,
    `prompt`) pair `ProprietaryLLMProvider.complete()` accepts.
    """
    if _LLM_BASE_URL:
        # Pass-through: forward the request to the upstream OpenAI-style endpoint.
        payload = req.model_dump(exclude_none=True)
        if _LLM_MODEL:
            payload["model"] = _LLM_MODEL
        headers = {"Content-Type": "application/json"}
        if _LLM_API_KEY:
            headers["Authorization"] = f"Bearer {_LLM_API_KEY}"
        url = f"{_LLM_BASE_URL}/chat/completions"
        try:
            with httpx.Client(timeout=_LLM_TIMEOUT) as client:
                upstream = client.post(url, json=payload, headers=headers)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"upstream error: {exc}")
        if upstream.status_code >= 400:
            # Surface the upstream status code + body so SIRA's retry
            # backoff has something to log. SIRA retries 3x on non-200.
            raise HTTPException(
                status_code=upstream.status_code,
                detail=f"upstream {upstream.status_code}: {upstream.text[:300]}",
            )
        return upstream.json()

    # Adapter mode — same behavior as the original shim.
    system_parts: list[str] = []
    prompt_parts: list[str] = []
    for m in req.messages:
        target = system_parts if m.role == "system" else prompt_parts
        if m.content:
            target.append(m.content)
    system = "\n\n".join(system_parts)
    prompt = "\n\n".join(prompt_parts)

    try:
        text = _provider.complete(
            prompt=prompt,
            system=system,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
    except NotImplementedError as exc:
        # Stub provider — surface clearly so the user knows what to fill in,
        # OR what to set NORA_LLM_BASE_URL to instead.
        raise HTTPException(status_code=501, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"provider error: {exc}")

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model or _provider.model or "proprietary",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": -1,
            "completion_tokens": -1,
            "total_tokens": -1,
        },
    }


@app.get("/healthz")
def healthz() -> dict:
    if _LLM_BASE_URL:
        return {
            "ok": True,
            "mode": "pass-through",
            "base_url": _LLM_BASE_URL,
            "model_override": _LLM_MODEL or None,
            "api_key_set": bool(_LLM_API_KEY),
        }
    return {
        "ok": True,
        "mode": "adapter",
        "model": _provider.model,
        "endpoint": _provider.endpoint,
        "calls": _provider.call_count,
    }
