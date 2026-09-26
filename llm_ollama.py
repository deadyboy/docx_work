from __future__ import annotations

"""Backward-compatible adapter from legacy extractor calls to the unified LLM client.

Existing extractors still import ``ollama_generate`` from this module.  The
historical function name is kept stable, while the actual backend is selected
per agent run (Ollama or vLLM).  A ContextVar avoids process-global backend
state leaking between concurrent runs.
"""

from contextlib import contextmanager
from contextvars import ContextVar
import os
import re
from typing import Iterator

from .llm_client import generate as _unified_generate
from .llm_client import loads_json

_BACKEND_OVERRIDE: ContextVar[str | None] = ContextVar(
    "docx_work_llm_backend", default=None
)


@contextmanager
def use_backend(backend: str) -> Iterator[None]:
    """Temporarily select the backend used by legacy extractor calls."""
    normalized = backend.lower()
    if normalized not in {"ollama", "vllm"}:
        raise ValueError(
            f"Unknown LLM backend {backend!r}. Choose 'ollama' or 'vllm'."
        )
    token = _BACKEND_OVERRIDE.set(normalized)
    try:
        yield
    finally:
        _BACKEND_OVERRIDE.reset(token)


def ollama_generate(
    model: str,
    prompt: str,
    num_predict: int = 8000,
    timeout_s: int = 1000,
) -> str:
    """Legacy entry point; dispatch to the selected unified backend."""
    backend = _BACKEND_OVERRIDE.get() or os.environ.get("LLM_BACKEND", "ollama")
    return _unified_generate(
        model=model,
        prompt=prompt,
        backend=backend,
        num_predict=num_predict,
        timeout_s=timeout_s,
    )


def extract_json_str(text: str) -> str:
    """Extract the outermost JSON object from text (legacy helper)."""
    if not text:
        return ""
    text = re.sub(r"^```json\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^```\s*", "", text, flags=re.MULTILINE)
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return ""
