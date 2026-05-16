"""OpenAI-compatible `/v1/chat/completions` shim that routes onto
`customizations/llm/proprietary_provider.ProprietaryLLMProvider`.

SIRA (`facebookresearch/sira`) hardcodes its LLM URL as
`http://127.0.0.1:{port}/v1/chat/completions` and constructs an
OpenAI-shape payload (`model`, `messages`, `max_tokens`, `temperature`,
optional `seed` / `chat_template_kwargs`). This shim accepts that exact
payload, collapses `messages` into the (`system`, `prompt`) pair our
provider expects, and re-envelopes the provider's string response into
the OpenAI `choices[0].message.content` shape SIRA reads.

Run from the repo root:

    uvicorn sandbox.shim.openai_shim:app --port 8030

Then in SIRA's hydra config, set `sglang.port=8030` and SIRA will
transparently route every enrichment / reranking call here. No SIRA
source modification is required — confirmed Phase 0.

The shim is sandbox-only — never imported by NORA's `core/` modules.
"""

from __future__ import annotations

import os
import time
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

from customizations.llm.proprietary_provider import ProprietaryLLMProvider


_provider = ProprietaryLLMProvider(
    model=os.getenv("NORA_PROPRIETARY_MODEL", ""),
    endpoint=os.getenv("NORA_PROPRIETARY_ENDPOINT", ""),
)


app = FastAPI(title="NORA proprietary-LLM shim for SIRA")


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
    """Translate one OpenAI chat-completions request onto the provider.

    Message collapse rule: every `role=system` message is concatenated
    into the `system` field (in arrival order, separated by a blank
    line). Every other role (`user` / `assistant` / `tool`) is
    concatenated into the `prompt` field in arrival order. SIRA's
    enrichment + reranking scripts only ever send a single `user`
    message, so the prompt typically reduces to one string and `system`
    is empty.
    """
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
        # Stub provider — surface clearly so the user knows what to fill in.
        raise HTTPException(status_code=501, detail=str(exc))
    except Exception as exc:
        # Any other provider error: 502 with the message; SIRA will retry per
        # its own backoff (`post_chat` retries up to 3x).
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
        # Token counts aren't surfaced by ProprietaryLLMProvider; SIRA
        # doesn't read them either, so -1 is a safe sentinel.
        "usage": {
            "prompt_tokens": -1,
            "completion_tokens": -1,
            "total_tokens": -1,
        },
    }


@app.get("/healthz")
def healthz() -> dict:
    return {
        "ok": True,
        "model": _provider.model,
        "endpoint": _provider.endpoint,
        "calls": _provider.call_count,
    }
