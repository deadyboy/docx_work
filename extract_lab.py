from __future__ import annotations

from typing import Dict, Any, List, Optional

from .llm_ollama import ollama_generate, loads_json
from .prompts import lab_prompt
from .prompts import score_prompt
from .qc import qc_item_basic
from .qc import filter_daily_items

def dedup_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for it in items:
        key = (
            it.get("date"),
            it.get("time"),
            it.get("value"),
            (it.get("unit") or "").lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def sort_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(items, key=lambda x: (x.get("date") or "9999-99-99", str(x.get("time") or "")))


def _normalize_items(items: Any) -> List[Dict[str, Any]]:
    if isinstance(items, list):
        return [x for x in items if isinstance(x, dict)]
    return []


def extract_lab_items(
    model: str,
    lab_name: str,
    aliases: List[str],
    unit_candidates: List[str],
    contexts: List[Dict[str, Any]],
    max_items: int = 50,
    num_predict: int = 8000,
    debug_dump_failures: bool = False,
) -> Dict[str, Any]:
    all_items: List[Dict[str, Any]] = []

    for ctx in contexts:
        ctx_text = ctx.get("text", "")
        if not ctx_text:
            continue

        prompt = lab_prompt(lab_name, aliases, ctx_text)
        raw = ollama_generate(model, prompt, num_predict=num_predict)
        js = loads_json(raw)
        items = _normalize_items(js.get("items"))

        # attach block_ids from context if model omitted or returned invalid
        ctx_block_ids = ctx.get("block_ids")

        for it in items:
            if isinstance(ctx_block_ids, list):
                it["block_ids"] = ctx_block_ids
                it["doc_type"] = ctx.get("doc_type")
            qc_item_basic(it, aliases=aliases, unit_candidates=unit_candidates, context_meta=ctx)

        items = [it for it in items if it.get("qc_pass")]
        all_items.extend(items)

    all_items = dedup_items(all_items)
    all_items = sort_items(all_items)
    all_items = filter_daily_items(all_items, threshold=7)
    all_items = all_items[:max_items]
    return {"items": all_items, "count": len(all_items)}

def extract_score_items(
    model: str,
    score_name: str,
    aliases: List[str],
    unit_candidates: List[str],
    contexts: List[Dict[str, Any]],
    max_items: int = 50,
    num_predict: int = 8000,
    debug_dump_failures: bool = False,
) -> Dict[str, Any]:
    all_items: List[Dict[str, Any]] = []

    for ctx in contexts:
        ctx_text = ctx.get("text", "")
        if not ctx_text:
            continue

        prompt = score_prompt(score_name, aliases, ctx_text)
        raw = ollama_generate(model, prompt, num_predict=num_predict)
        js = loads_json(raw)
        items = _normalize_items(js.get("items"))

        # attach block_ids from context if model omitted or returned invalid
        ctx_block_ids = ctx.get("block_ids")

        for it in items:
            if isinstance(ctx_block_ids, list):
                it["block_ids"] = ctx_block_ids
                it["doc_type"] = ctx.get("doc_type")
            qc_item_basic(it, aliases=aliases, unit_candidates=unit_candidates, context_meta=ctx)

        items = [it for it in items if it.get("qc_pass")]
        all_items.extend(items)

    all_items = dedup_items(all_items)
    all_items = sort_items(all_items)
    all_items = filter_daily_items(all_items, threshold=7)
    all_items = all_items[:max_items]

    return {"items": all_items, "count": len(all_items)}

