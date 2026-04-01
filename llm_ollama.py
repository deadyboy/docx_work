from __future__ import annotations

import json
import re
from typing import Any, Dict
import os
import requests

try:
    import json_repair  # optional
except Exception:
    json_repair = None


_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "127.0.0.1")
_OLLAMA_PORT = os.environ.get("OLLAMA_PORT", "11434")
OLLAMA_URL = f"http://{_OLLAMA_HOST}:{_OLLAMA_PORT}/api/generate"


def ollama_generate(model: str, prompt: str, num_predict: int = 8000, timeout_s: int = 1000) -> str:
    """Call Ollama /api/generate.

    Notes:
    - We request `format: json`, but some models may still emit extra text.
    - We set deterministic decoding options to reduce variance.
    """
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
            # Keep ctx configurable; if your model supports larger ctx, raise here.
            "num_ctx": 8192,
        },
    }

    r = requests.post(OLLAMA_URL, json=payload, timeout=timeout_s)
    r.raise_for_status()
    data = r.json()
    return data.get("response", "")


def extract_json_str(text: str) -> str:
    """Extract the outermost JSON object from text."""
    if not text:
        return ""

    # strip fenced code blocks if present
    text = re.sub(r"^```json\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^```\s*", "", text, flags=re.MULTILINE)
    text = text.strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return ""


def loads_json(text: str) -> Dict[str, Any]:
    """
    Parse model output into dict.

    关键：解析失败必须可区分（不能再等价于“items为空”）。
    - _parse_error: bool
    - _error: str
    - _raw_excerpt: str（截断）
    同时保留 legacy keys items/count，保证 lab/panel 不改也能跑。
    """
    json_str = extract_json_str(text)
    if not json_str:
        return {
            "_parse_error": True,
            "_error": "no_json_object",
            "_raw_excerpt": _raw_excerpt(text),
            "items": [],
            "count": 0,
        }

    last_err = None
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
    
def _raw_excerpt(text: str, max_len: int = 2000) -> str:
    if not text:
        return ""
    t = text.strip()
    return t[:max_len] if len(t) > max_len else t
