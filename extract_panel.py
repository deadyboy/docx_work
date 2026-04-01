from __future__ import annotations

import json
import re
from typing import Dict, Any, List, Optional, Tuple

from .llm_ollama import ollama_generate, loads_json
from .prompts import panel_prompt
from .qc import parse_date_from_text  # 你 qc.py 里已有这个函数；如果没导出就复制一份过来
from .qc import filter_daily_items

NUM_RE = re.compile(r"-?(?:\d+(?:\.\d+)?|\.\d+)")
SENT_SPLIT = re.compile(r"[；;。\n]")

def _trim(s: str, max_len: int = 180) -> str:
    if not s:
        return ""
    s = s.strip()
    if len(s) <= max_len:
        return s
    tail = s[:max_len]
    m = SENT_SPLIT.search(tail[90:])
    if m:
        return tail[: 90 + m.start() + 1].strip()
    return tail.strip()

def _norm(s: str) -> str:
    if not s:
        return ""
    return (s.replace("／", "/")
             .replace("－", "-").replace("–", "-").replace("—", "-")
             .replace("％", "%"))

def _has_trigger(text: str, triggers: List[str]) -> bool:
    t = _norm(text).lower()
    return any(_norm(x).lower() in t for x in triggers)

def _count_present(results: Dict[str, Any]) -> int:
    n = 0
    for v in (results or {}).values():
        if isinstance(v, dict) and v.get("value") is not None:
            n += 1
    return n

def _norm_unit(u: str) -> str:
    return (u or "").strip().lower()

def _norm_value(v: Any) -> str:
    """
    保留原值但做轻量规范化，保证去重稳定：
    - 去掉空格
    - 统一全角符号
    - 统一大小写
    """
    if v is None:
        return ""
    s = str(v).strip()
    s = s.replace("＞", ">").replace("＜", "<").replace("＝", "=")
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", "", s)  # 去空格
    return s.lower()

def _dedup_key(date: str, results: Dict[str, Any]) -> tuple:
    items = []
    for k, v in (results or {}).items():
        if not isinstance(v, dict):
            continue
        raw_val = v.get("value")
        if raw_val is None:
            continue
        items.append((k, _norm_value(raw_val), _norm_unit(v.get("unit"))))
    items.sort()
    return (date, tuple(items))

def extract_panel_items(
    *,
    model: str,
    panel_name: str,
    triggers: List[str],
    analytes: List[Dict[str, Any]],          # list of {"key","aliases","unit_candidates"}
    min_present: int,
    contexts: List[Dict[str, Any]],
    max_items: int = 50,
) -> Dict[str, Any]:
    # 生成 analytes_desc（给 prompt 看）
    lines = []
    keys = []
    for a in analytes:
        keys.append(a["key"])
        alias_str = "、".join(a["aliases"])
        unit_str = "、".join(a.get("unit_candidates", [])) or "（可缺省）"
        lines.append(f"- {a['key']}: 关键词={alias_str}；单位候选={unit_str}")
    analytes_desc = "\n".join(lines)

    out_items: List[Dict[str, Any]] = []
    seen = set()

    for ctx in contexts:
        ctx_text = ctx.get("text", "")
        prompt = panel_prompt(panel_name, triggers, analytes_desc, min_present, ctx_text)

        raw = ollama_generate(model=model, prompt=prompt)

        data = loads_json(raw)
        if not isinstance(data, dict):
            continue

        items = data.get("items", [])
        if not isinstance(items, list):
            continue

        ctx_block_ids = ctx.get("block_ids", [])
        doc_type = ctx.get("doc_type")
        anchor = ctx.get("primary_anchor")  # "YYYY-MM-DD HH:MM:SS"

        for it in items:
            if not isinstance(it, dict):
                continue

            # evidence 裁剪
            ev = _trim(it.get("evidence", ""))
            it["evidence"] = ev

            # 强制覆盖定位信息（防编造）
            it["block_ids"] = ctx_block_ids if isinstance(ctx_block_ids, list) else []
            it["doc_type"] = doc_type

            # results 结构保证含所有KEY
            results = it.get("results")
            if not isinstance(results, dict):
                continue
            for k in keys:
                if k not in results or not isinstance(results[k], dict):
                    results[k] = {"value": None, "unit": None}

            # date 回填：证据有日期用证据；否则用 anchor
            d = parse_date_from_text(ev)
            if not d and anchor:
                d = str(anchor)[:10]
            if not d:
                continue
            it["date"] = d
            it["time"] = None

            # Panel QC 1：必须命中 trigger（在 evidence 或 context 内任一即可）
            if not (_has_trigger(ev, triggers) or _has_trigger(ctx_text, triggers)):
                continue

            # Panel QC 2：至少 min_present 个指标非空
            if _count_present(results) < min_present:
                continue

            # 去重
            k = _dedup_key(d, results)
            if k in seen:
                continue
            seen.add(k)

            out_items.append(it)
            if len(out_items) >= max_items:
                break

        if len(out_items) >= max_items:
            break

    def _sort_key(it: Dict[str, Any]):
        d = it.get("date") or ""
        t = it.get("time") or ""
        ev = it.get("evidence") or ""
        return (d, t, ev)

    out_items.sort(key=_sort_key)
    final_items = filter_daily_items(out_items, threshold=7)
    return {"items": final_items[:max_items], "count": len(final_items[:max_items])}
