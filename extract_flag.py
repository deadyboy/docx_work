# src/extract_flags.py
# from __future__ import annotations
# from typing import Any, Dict, List, Optional, Tuple
# import os

# from .llm_ollama import ollama_generate, loads_json

# YESNO = ("是", "否")

# def _render_flags_schema(fields: List[Tuple[str, str]]) -> str:
#     """
#     fields: [(field_name, field_type), ...]
#     field_type: "yesno" | "text"
#     """
#     lines = []
#     for name, tp in fields:
#         if tp == "yesno":
#             lines.append(f'    "{name}": "是"|"否"|null,')
#         else:
#             lines.append(f'    "{name}": string|null,')
#     # 去掉最后一个逗号
#     if lines:
#         lines[-1] = lines[-1].rstrip(",")
#     return "\n".join(lines)

# def flags_prompt(fields: List[Tuple[str, str]], context: str) -> str:
#     schema = _render_flags_schema(fields)
#     return f"""你是医疗文本结构化抽取器。

# 任务：从【输入文本】中抽取以下字段。找不到则填 null，禁止编造。
# 每个字段如果不是 null，必须给出 evidence_map[field]：连续原文片段（<=160字）可以直接支持该字段取值。

# 规则：
# 1) 只能依据输入文本，不得推断。
# 2) “是否类”字段只能输出：是 / 否 / null。
# 3) 若文本中存在明确否认（如“否认高血压史”），输出“否”，并给出对应 evidence。
# 4) “其他诊断”若文本出现“另有/合并/诊断：xxx”等，抽取主要内容；没有则 null。
# 5) 输出必须是严格 JSON，不要输出解释性文字。

# 输出 JSON：
# {{
#   "data": {{
# {schema}
#   }},
#   "evidence_map": {{
#     "<字段名>": "<连续原文片段>"
#   }}
# }}

# 【输入文本】
# {context}
# """

# def _accept_value(field_type: str, v: Any) -> Optional[Any]:
#     if v is None:
#         return None
#     if field_type == "yesno":
#         if isinstance(v, str):
#             vv = v.strip()
#             if vv in YESNO:
#                 return vv
#         return None
#     # text
#     if isinstance(v, str):
#         s = v.strip()
#         return s if s else None
#     return None

# def extract_flags_items(
#     *,
#     model: str,
#     contexts: List[Dict[str, Any]],
#     fields: List[Tuple[str, str]],
#     max_ctx: int = 12,
#     stop_ratio: float = 0.85,
# ) -> Dict[str, Any]:
#     """
#     最简合并策略：
#     - 逐 ctx 调用 LLM
#     - 只“补 None”，不覆盖已填字段
#     - 非空字段必须有 evidence_map 对应条目，否则忽略
#     - 达到 stop_ratio 覆盖率后提前停止
#     """
#     total = len(fields)
#     merged: Dict[str, Any] = {name: None for name, _ in fields}
#     merged_evm: Dict[str, str] = {}

#     used_doc_types: List[str] = []
#     block_ids_union: List[int] = []

#     def filled_count() -> int:
#         return sum(1 for k in merged if merged[k] is not None)

#     for ctx in contexts[:max_ctx]:
#         prompt = flags_prompt(fields, ctx.get("text", ""))
#         raw = ollama_generate(model=model, prompt=prompt)
#         obj = loads_json(raw)
#         if not isinstance(obj, dict):
#             continue

#         data = obj.get("data") or {}
#         evm = obj.get("evidence_map") or {}
#         if not isinstance(data, dict) or not isinstance(evm, dict):
#             continue

#         changed = False
#         for name, tp in fields:
#             if merged.get(name) is not None:
#                 continue
#             v = _accept_value(tp, data.get(name))
#             if v is None:
#                 continue
#             ev = evm.get(name)
#             if not isinstance(ev, str) or not ev.strip():
#                 continue
#             merged[name] = v
#             merged_evm[name] = ev.strip()
#             changed = True

#         if changed:
#             dt = ctx.get("doc_type")
#             if isinstance(dt, str) and dt and dt not in used_doc_types:
#                 used_doc_types.append(dt)
#             bids = ctx.get("block_ids") or []
#             if isinstance(bids, list):
#                 for b in bids:
#                     if isinstance(b, int) and b not in block_ids_union:
#                         block_ids_union.append(b)

#         if total > 0 and filled_count() / total >= stop_ratio:
#             break

#     return {
#         "data": merged,
#         "evidence_map": merged_evm,
#         "doc_types": used_doc_types,
#         "block_ids": block_ids_union,
#     }


# src/extract_flags.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple

from .llm_ollama import ollama_generate, loads_json
from .prompts import flags_prompt

# extract_flag.py

YESNO = ("是", "否")

NEGATION_CUES = (
    "否认", "无", "未见", "排除", "不考虑", "不支持", "未予", "未行", "未用", "停用",
    "未发现", "未提示", "未发生", "未出现", "不伴", "未合并", "不合并",
)

AFFIRM_CUES = (
    "诊断", "考虑", "提示", "支持", "合并", "既往", "病史", "患有", "明确", "证实",
    "予以", "给予", "使用", "已用", "已予", "启动", "置入", "上机", "行",
)

def _has_any(text: str, cues) -> bool:
    if not text:
        return False
    t = text.strip()
    return any(c in t for c in cues)

def _yesno_strength(val: str, evidence: str) -> int:
    """
    0: 无效
    1: 有值但证据缺乏明确 cue（保守）
    2: 有值且证据含对应 cue（更可信）
    """
    if val not in YESNO or not evidence:
        return 0
    if val == "否":
        return 2 if _has_any(evidence, NEGATION_CUES) else 1
    return 2 if _has_any(evidence, AFFIRM_CUES) else 1

def _should_override_yesno(old_v: str, old_ev: str, new_v: str, new_ev: str) -> bool:
    # 只在“新证据更强”时允许覆盖（稳定且可纠错）
    return _yesno_strength(new_v, new_ev) > _yesno_strength(old_v, old_ev)


def _accept_value(field_type: str, v: Any) -> Any:
    if v is None:
        return None
    if field_type == "yesno":
        if isinstance(v, str) and v.strip() in YESNO:
            return v.strip()
        return None
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    return None

def extract_flags_items(
    *,
    model: str,
    contexts: List[Dict[str, Any]],
    fields: List[Tuple[str, str]],
    domain: str = "general",
    max_ctx: int = 12,
    stop_ratio: float = 0.85,
) -> Dict[str, Any]:
    merged = {name: None for name, _ in fields}
    evm: Dict[str, str] = {}
    src_map: Dict[str, Dict[str, Any]] = {}   # M2：字段来源回溯

    meta = {"contexts_used": 0, "parse_errors": 0}

    def filled_ratio() -> float:
        total = len(fields) or 1
        filled = sum(1 for k in merged if merged[k] is not None)
        return filled / total

    for ctx in contexts[:max_ctx]:
        prompt = flags_prompt(fields, ctx.get("text", ""), domain=domain)
        raw = ollama_generate(model=model, prompt=prompt)
        obj = loads_json(raw)
        
        meta["contexts_used"] += 1

        # (1) 解析失败显式统计：不再伪装成“无结果”
        if isinstance(obj, dict) and obj.get("_parse_error"):
            meta["parse_errors"] += 1
            continue
        if not isinstance(obj, dict):
            meta["parse_errors"] += 1
            continue

        data = obj.get("data")
        em = obj.get("evidence_map")
        if not isinstance(data, dict) or not isinstance(em, dict):
            meta["parse_errors"] += 1
            continue

        doc_type = ctx.get("doc_type")
        block_ids = ctx.get("block_ids")

        for name, tp in fields:
            v = _accept_value(tp, data.get(name))
            if v is None:
                continue
            evidence = em.get(name)
            if not isinstance(evidence, str) or not evidence.strip():
                continue
            evidence = evidence.strip()

            # 空位：直接填
            if merged[name] is None:
                merged[name] = v
                evm[name] = evidence
                src_map[name] = {"doc_type": doc_type, "block_ids": block_ids}
                continue

            # (2) yes/no：允许“更强证据”纠错覆盖
            if tp == "yesno":
                old_v = merged[name]
                old_ev = evm.get(name, "")
                if isinstance(old_v, str) and _should_override_yesno(old_v, old_ev, v, evidence):
                    merged[name] = v
                    evm[name] = evidence
                    src_map[name] = {"doc_type": doc_type, "block_ids": block_ids}

        if filled_ratio() >= stop_ratio:
            break

    return {
        "data": merged,
        "evidence_map": evm,
        "source_map": src_map,   # M2
        "meta": meta,            # (1) parse_errors 可观测化
    }
