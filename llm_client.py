"""Unified LLM client: Ollama + vLLM (OpenAI-compatible) + multimodal.

This module provides a single ``generate()`` entry-point that works with:

* **Ollama** – local REST API at ``/api/generate`` (text) or ``/api/chat`` (vision).
* **vLLM** – OpenAI-compatible endpoint at ``/v1/chat/completions``.

The caller selects the backend via the ``backend`` parameter or via the
``LLM_BACKEND`` environment variable (values: ``"ollama"`` / ``"vllm"``).

Backward-compatibility note
----------------------------
The original ``llm_ollama.py`` remains untouched so that all existing code
continues to work without modification.  New agent code should import from
this module instead.

Environment variables
---------------------
``LLM_BACKEND``         ``"ollama"`` (default) or ``"vllm"``
``OLLAMA_HOST``         host for Ollama (default ``127.0.0.1``)
``OLLAMA_PORT``         port for Ollama (default ``11434``)
``VLLM_BASE_URL``       full base URL for vLLM (default ``http://127.0.0.1:8000``)
``VLLM_API_KEY``        API key for vLLM / OpenAI (default ``"EMPTY"``)
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import requests

try:
    import json_repair  # optional – improves robustness against partial JSON
except Exception:
    json_repair = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_BACKEND = os.environ.get("LLM_BACKEND", "ollama").lower()

_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "127.0.0.1")
_OLLAMA_PORT = os.environ.get("OLLAMA_PORT", "11434")
_OLLAMA_GENERATE_URL = f"http://{_OLLAMA_HOST}:{_OLLAMA_PORT}/api/generate"
_OLLAMA_CHAT_URL = f"http://{_OLLAMA_HOST}:{_OLLAMA_PORT}/api/chat"

_VLLM_BASE_URL = os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8000")
_VLLM_API_KEY = os.environ.get("VLLM_API_KEY", "EMPTY")
_VLLM_CHAT_URL = f"{_VLLM_BASE_URL}/v1/chat/completions"

# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def generate(
    model: str,
    prompt: str,
    *,
    backend: Optional[str] = None,
    num_predict: int = 8000,
    timeout_s: int = 1000,
    image_paths: Optional[List[Union[str, Path]]] = None,
) -> str:
    """Generate a response from a language model.

    Parameters
    ----------
    model:
        Model name as known to the chosen backend (e.g. ``"qwen3:8b"`` for
        Ollama or ``"Qwen/Qwen2.5-7B-Instruct"`` for vLLM).
    prompt:
        The full prompt string to send to the model.
    backend:
        ``"ollama"`` or ``"vllm"``.  When ``None`` the value of the
        ``LLM_BACKEND`` environment variable is used (defaults to
        ``"ollama"``).
    num_predict:
        Maximum number of tokens to generate.
    timeout_s:
        HTTP request timeout in seconds.
    image_paths:
        Optional list of image file paths to include in a multimodal request.
        Only supported when ``backend="ollama"`` with a vision model or when
        ``backend="vllm"`` with a vision model.

    Returns
    -------
    str
        Raw text response from the model.
    """
    backend = (backend or _BACKEND).lower()

    if backend == "ollama":
        return _ollama_generate(
            model=model,
            prompt=prompt,
            num_predict=num_predict,
            timeout_s=timeout_s,
            image_paths=image_paths,
        )
    elif backend == "vllm":
        return _vllm_generate(
            model=model,
            prompt=prompt,
            num_predict=num_predict,
            timeout_s=timeout_s,
            image_paths=image_paths,
        )
    else:
        raise ValueError(
            f"Unknown LLM backend '{backend}'. Choose 'ollama' or 'vllm'."
        )


def loads_json(text: str) -> Dict[str, Any]:
    """Parse model output into a dict.

    On parse failure, returns a sentinel dict with ``_parse_error=True`` so
    callers can distinguish "no result" from "parse error" without raising.
    """
    json_str = _extract_json_str(text)
    if not json_str:
        return {
            "_parse_error": True,
            "_error": "no_json_object",
            "_raw_excerpt": _raw_excerpt(text),
            "items": [],
            "count": 0,
        }

    last_err: Optional[str] = None
    if json_repair is not None:
        try:
            obj = json_repair.loads(json_str)
            if isinstance(obj, dict):
                obj.setdefault("_parse_error", False)
                return obj
            last_err = "json_repair_returned_non_object"
        except Exception as e:
            last_err = f"json_repair_failed: {type(e).__name__}"

    try:
        obj = json.loads(json_str)
        if isinstance(obj, dict):
            obj.setdefault("_parse_error", False)
            return obj
        return {
            "_parse_error": True,
            "_error": "json_not_object",
            "_raw_excerpt": _raw_excerpt(text),
            "items": [],
            "count": 0,
        }
    except Exception as e:
        return {
            "_parse_error": True,
            "_error": last_err or f"json_loads_failed: {type(e).__name__}",
            "_raw_excerpt": _raw_excerpt(text),
            "items": [],
            "count": 0,
        }


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------


def _ollama_generate(
    model: str,
    prompt: str,
    num_predict: int,
    timeout_s: int,
    image_paths: Optional[List[Union[str, Path]]] = None,
) -> str:
    """Call the Ollama API (text or vision)."""
    if image_paths:
        # Vision mode – use /api/chat with base64-encoded images
        images_b64 = [_load_image_b64(p) for p in image_paths]
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": images_b64,
                }
            ],
            "stream": False,
            "options": {
                "temperature": 0,
                "num_predict": num_predict,
            },
        }
        r = requests.post(_OLLAMA_CHAT_URL, json=payload, timeout=timeout_s)
        r.raise_for_status()
        data = r.json()
        return data.get("message", {}).get("content", "")
    else:
        # Text mode – use /api/generate with JSON format enforcement
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "top_k": 1,
                "top_p": 1,
                "typical_p": 1,
                "mirostat": 0,
                "repeat_penalty": 1,
                "num_predict": num_predict,
                "num_ctx": 8192,
            },
        }
        r = requests.post(_OLLAMA_GENERATE_URL, json=payload, timeout=timeout_s)
        r.raise_for_status()
        data = r.json()
        return data.get("response", "")


def _vllm_generate(
    model: str,
    prompt: str,
    num_predict: int,
    timeout_s: int,
    image_paths: Optional[List[Union[str, Path]]] = None,
) -> str:
    """Call a vLLM / OpenAI-compatible chat completions endpoint."""
    headers = {
        "Authorization": f"Bearer {_VLLM_API_KEY}",
        "Content-Type": "application/json",
    }

    if image_paths:
        # Multimodal: include images in message content
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for p in image_paths:
            b64 = _load_image_b64(p)
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                }
            )
        messages = [{"role": "user", "content": content}]
    else:
        messages = [{"role": "user", "content": prompt}]

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": num_predict,
        "temperature": 0,
        # Ask for JSON output when no images are involved
        **({"response_format": {"type": "json_object"}} if not image_paths else {}),
    }

    r = requests.post(_VLLM_CHAT_URL, json=payload, headers=headers, timeout=timeout_s)
    r.raise_for_status()
    data = r.json()
    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "")
    return ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_image_b64(path: Union[str, Path]) -> str:
    """Read an image file and return a base64-encoded string."""
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("utf-8")


def _extract_json_str(text: str) -> str:
    """Extract the outermost JSON object from arbitrary model output."""
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


def _raw_excerpt(text: str, max_len: int = 2000) -> str:
    if not text:
        return ""
    t = text.strip()
    return t[:max_len] if len(t) > max_len else t
