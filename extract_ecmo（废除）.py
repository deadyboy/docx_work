# # from __future__ import annotations

# # from typing import Dict, Any, List, Optional, Tuple
# # import os

# # from .llm_ollama import ollama_generate, loads_json
# # from .prompts import ecmo_bundle_prompt
# # # from .debug_dump import dump_contexts


# # ECMO_FIELDS = [
# #     "ECMO方式",
# #     "ECMO上机时间",
# #     "ECMO下机时间",
# #     "ECMO 机器记录内容",
# #     "ECMO 下机记录时间",
# #     "ECMO 下机记录内容",
# #     "是否ECMO脱机成功"
# # ]


# # def _as_str_or_none(x: Any) -> Optional[str]:
# #     if x is None:
# #         return None
# #     if isinstance(x, str):
# #         s = x.strip()
# #         return s if s else None
# #     # 允许模型偶尔输出数字/其它类型：转字符串保留原样
# #     return str(x).strip() or None


# # def _trim_ev(s: Optional[str], max_len: int = 180) -> Optional[str]:
# #     if not s:
# #         return None
# #     t = s.strip()
# #     return t[:max_len] if len(t) > max_len else t


# # def _score_evidence(field: str, value: Optional[str], ev: Optional[str]) -> int:
# #     """
# #     决策“冲突时选谁”：分数越高越可信。
# #     很保守，不做复杂NLP。
# #     """
# #     if not value or not ev:
# #         return 0

# #     ev_l = ev.lower()
# #     score = 0

# #     # 基础：证据非空
# #     score += 10

# #     # 字段相关关键词加分
# #     if field == "ECMO方式":
# #         if "ecmo" in ev_l:
# #             score += 5
# #         if "v-a" in ev_l or "va" in ev_l or "v-v" in ev_l or "vv" in ev_l:
# #             score += 5

# #     if "上机" in field:
# #         if "上机" in ev or "置入" in ev or "启动" in ev:
# #             score += 5

# #     if ("下机" in field) or ("撤机" in (value or "")):
# #         if "下机" in ev or "撤机" in ev or "离机" in ev:
# #             score += 5

# #     if "机器记录" in field:
# #         if "转速" in ev or "流量" in ev or "回路" in ev or "rpm" in ev_l:
# #             score += 5

# #     # 值是否出现在证据里（强加分）
# #     if value and value in ev:
# #         score += 8

# #     # 证据过短扣分（可能太碎）
# #     if len(ev) < 12:
# #         score -= 3

# #     return score


# # def _merge_one(
# #     merged_data: Dict[str, Optional[str]],
# #     merged_ev: Dict[str, Optional[str]],
# #     merged_src: Dict[str, Dict[str, Any]],
# #     new_data: Dict[str, Optional[str]],
# #     new_ev: Dict[str, Optional[str]],
# #     ctx: Dict[str, Any],
# # ) -> None:
# #     """
# #     合并策略：每个字段只保留一个最终值。
# #     - 若当前为空且新值非空：直接用新值
# #     - 若二者都非空：用 evidence score 更高者
# #     """
# #     doc_type = ctx.get("doc_type")
# #     block_ids = ctx.get("block_ids")

# #     for f in ECMO_FIELDS:
# #         v_new = _as_str_or_none(new_data.get(f))
# #         ev_new = _trim_ev(new_ev.get(f))

# #         # 没新值就跳过
# #         if v_new is None and ev_new is None:
# #             continue

# #         v_old = merged_data.get(f)
# #         ev_old = merged_ev.get(f)

# #         if v_old is None:
# #             merged_data[f] = v_new
# #             merged_ev[f] = ev_new
# #             merged_src[f] = {"doc_type": doc_type, "block_ids": block_ids}
# #             continue

# #         # old 非空，但 new 为空：保留 old
# #         if v_new is None:
# #             continue

# #         # 二者都非空：择优
# #         s_old = _score_evidence(f, v_old, ev_old)
# #         s_new = _score_evidence(f, v_new, ev_new)

# #         if s_new > s_old:
# #             merged_data[f] = v_new
# #             merged_ev[f] = ev_new
# #             merged_src[f] = {"doc_type": doc_type, "block_ids": block_ids}


# # def extract_ecmo_bundle(
# #     *,
# #     model: str,
# #     contexts: List[Dict[str, Any]],
# #     max_ctx: int = 12,
# #     num_predict: int = 8000,
# #     dump_contexts_dir: Optional[str] = None,
# # ) -> Dict[str, Any]:
# #     """
# #     ECMO 专组抽取：在多个contexts上跑，最后合并成一个 data/evidence_map。

# #     max_ctx:
# #       - 这里不是“只取6个就一定够”，而是为了控制调用次数。
# #       - ECMO信息通常在“病程录/操作记录/出院记录”的少数几处集中出现；
# #         先用 recall 命中的 contexts 即可覆盖大部分病例。
# #       - 你若遇到非常分散的病例，可以把 max_ctx 提到 20 或更多。
# #     """

# #     # dump contexts 供你调试（只dump召回后的，不dump全量blocks）
# #     # if dump_contexts_dir:
# #     #     os.makedirs(dump_contexts_dir, exist_ok=True)
# #     #     dump_contexts(contexts, os.path.join(dump_contexts_dir, "contexts_ECMO.txt"))

# #     merged_data: Dict[str, Optional[str]] = {f: None for f in ECMO_FIELDS}
# #     merged_ev: Dict[str, Optional[str]] = {f: None for f in ECMO_FIELDS}
# #     merged_src: Dict[str, Dict[str, Any]] = {}
# #     meta = {"contexts_used": 0, "parse_errors": 0}

# #     used = 0
# #     for ctx in contexts[:max_ctx]:
# #         ctx_text = ctx.get("text", "")
# #         if not ctx_text:
# #             continue

# #         prompt = ecmo_bundle_prompt(ctx_text)
# #         raw = ollama_generate(model, prompt, num_predict=num_predict)
# #         js = loads_json(raw)
# #         meta["contexts_used"] += 1
# #         if isinstance(js, dict) and js.get("_parse_error"):
# #             meta["parse_errors"] += 1
# #             continue
# #         data = js.get("data") if isinstance(js, dict) else None
# #         evm = js.get("evidence_map") if isinstance(js, dict) else None
# #         if not isinstance(data, dict) or not isinstance(evm, dict):
# #             meta["parse_errors"] += 1
# #             continue


# #         # 只保留我们定义的 7 个字段
# #         data_norm = {f: _as_str_or_none(data.get(f)) for f in ECMO_FIELDS}
# #         ev_norm = {f: _trim_ev(_as_str_or_none(evm.get(f))) for f in ECMO_FIELDS}

# #         _merge_one(merged_data, merged_ev, merged_src, data_norm, ev_norm, ctx)
# #         used += 1

# #     filled = sum(1 for f in ECMO_FIELDS if merged_data.get(f) is not None)

# #     return {
# #         "data": merged_data,
# #         "evidence_map": merged_ev,
# #         "source_map": merged_src,          # 每个字段来源：doc_type + block_ids（用于回溯）
# #         "contexts_used": used,
# #         "count": filled,                   # 7字段中填上的数量
# #         "meta": meta,
# #     }

# # from __future__ import annotations
# # from typing import Dict, Any, List, Optional
# # from .llm_ollama import ollama_generate, loads_json
# # from .prompts import ecmo_bundle_prompt

# # # 这里只写 LLM 负责提取的字段
# # ECMO_LLM_FIELDS = [
# #     "ECMO方式",
# #     "ECMO下机记录时间",
# #     "ECMO下机记录内容",
# #     "是否ECMO脱机成功"
# # ]

# # def _as_str_or_none(x: Any) -> Optional[str]:
# #     if x is None:
# #         return None
# #     if isinstance(x, str):
# #         s = x.strip()
# #         return s if s else None
# #     return str(x).strip() or None

# # def extract_ecmo_bundle(
# #     *,
# #     model: str,
# #     contexts: List[Dict[str, Any]],
# #     max_ctx: int = 12,
# # ) -> Dict[str, Any]:
    
# #     # 用来临时收集不同文档类型的提取结果，方便做交叉验证
# #     collected_data = {"course": [], "big": []}
    
# #     meta = {"contexts_used": 0, "parse_errors": 0}

# #     # 1. 逐个 Context 调用 LLM
# #     for ctx in contexts[:max_ctx]:
# #         ctx_text = ctx.get("text", "")
# #         if not ctx_text:
# #             continue

# #         doc_type = ctx.get("doc_type")
# #         # 确保是我们关注的类型
# #         if doc_type not in ["course", "big"]:
# #             continue

# #         prompt = ecmo_bundle_prompt(ctx_text)
# #         raw = ollama_generate(model, prompt, num_predict=8000)
# #         js = loads_json(raw)
# #         meta["contexts_used"] += 1
        
# #         if not isinstance(js, dict) or js.get("_parse_error"):
# #             meta["parse_errors"] += 1
# #             continue
            
# #         data = js.get("data")
# #         evm = js.get("evidence_map")
# #         if not isinstance(data, dict) or not isinstance(evm, dict):
# #             meta["parse_errors"] += 1
# #             continue

# #         # 把提取到的非空结果按 doc_type 收集起来
# #         parsed = {f: _as_str_or_none(data.get(f)) for f in ECMO_LLM_FIELDS}
# #         evidence = {f: _as_str_or_none(evm.get(f)) for f in ECMO_LLM_FIELDS}
        
# #         # 只要有一项有值，就存起来
# #         if any(v is not None for v in parsed.values()):
# #             collected_data[doc_type].append({"data": parsed, "evidence": evidence, "ctx": ctx})

# #     # 2. 交叉验证与合并逻辑 (Cross-Validation)
# #     merged_data = {f: None for f in ECMO_LLM_FIELDS}
# #     merged_ev = {f: None for f in ECMO_LLM_FIELDS}
    
# #     # 提取所有成功标志
# #     success_flags_course = [item["data"]["是否ECMO脱机成功"] for item in collected_data["course"] if item["data"]["是否ECMO脱机成功"] in ["是", "否"]]
# #     success_flags_big = [item["data"]["是否ECMO脱机成功"] for item in collected_data["big"] if item["data"]["是否ECMO脱机成功"] in ["是", "否"]]
    
# #     # 【交叉验证规则：是否脱机成功】
# #     # 如果两边都有记录且都说"是"，那就是"是"。如果冲突或只有一边，你可以退化为"以病程录为准"，这里我们采取：只要有明确说是的，且没有矛盾，就算"是"
# #     all_flags = success_flags_course + success_flags_big
# #     if "是" in all_flags and "否" not in all_flags:
# #         merged_data["是否ECMO脱机成功"] = "是"
# #     elif "否" in all_flags and "是" not in all_flags:
# #         merged_data["是否ECMO脱机成功"] = "否"
# #     elif "是" in all_flags and "否" in all_flags:
# #         merged_data["是否ECMO脱机成功"] = "冲突(需人工核对)"

# #     # 【合并拼接规则：下机内容与时间】
# #     # 把病程录和大病历里的下机内容拼接到一起，供医生溯源
# #     for field in ["ECMO下机记录内容", "ECMO下机记录时间", "ECMO方式"]:
# #         texts = []
# #         evidences = []
# #         for doc_type in ["big", "course"]:
# #             for item in collected_data[doc_type]:
# #                 val = item["data"][field]
# #                 if val and val not in texts: # 简单去重
# #                     prefix = "【大病历】" if doc_type == "big" else "【病程录】"
# #                     texts.append(f"{prefix}{val}")
# #                     evidences.append(f"{prefix}{item['evidence'][field]}")
        
# #         if texts:
# #             merged_data[field] = " | ".join(texts)
# #             merged_ev[field] = " | ".join(evidences)

# #     return {
# #         "data": merged_data,
# #         "evidence_map": merged_ev,
# #         "meta": meta,
# #     }
# from __future__ import annotations
# import os
# import json
# from typing import Dict, Any, List, Optional
# from .llm_ollama import ollama_generate, loads_json
# from .prompts import ecmo_bundle_prompt

# # 这里只写 LLM 负责提取的字段
# ECMO_LLM_FIELDS = [
#     "ECMO方式",
#     "ECMO下机记录时间",
#     "ECMO下机记录内容",
#     "是否ECMO脱机成功"
# ]

# def _as_str_or_none(x: Any) -> Optional[str]:
#     if x is None:
#         return None
#     if isinstance(x, str):
#         s = x.strip()
#         return s if s else None
#     return str(x).strip() or None

# def extract_ecmo_bundle(
#     *,
#     model: str,
#     contexts: List[Dict[str, Any]],
#     max_ctx: int = 12,
#     dump_contexts_dir: Optional[str] = None, # 【新增参数】：接收隔离的 dump 目录
# ) -> Dict[str, Any]:
    
#     # 用来临时收集不同文档类型的提取结果，方便做交叉验证
#     collected_data = {"course": [], "big": []}
#     meta = {"contexts_used": 0, "parse_errors": 0}

#     # 1. 逐个 Context 调用 LLM
#     for ctx in contexts[:max_ctx]:
#         ctx_text = ctx.get("text", "")
#         if not ctx_text:
#             continue

#         doc_type = ctx.get("doc_type")
#         if doc_type not in ["course", "big"]:
#             continue

#         prompt = ecmo_bundle_prompt(ctx_text)
#         raw = ollama_generate(model, prompt, num_predict=8000)
#         js = loads_json(raw)
#         meta["contexts_used"] += 1
        
#         if not isinstance(js, dict) or js.get("_parse_error"):
#             meta["parse_errors"] += 1
#             continue
            
#         data = js.get("data")
#         evm = js.get("evidence_map")
#         if not isinstance(data, dict) or not isinstance(evm, dict):
#             meta["parse_errors"] += 1
#             continue

#         # 把提取到的非空结果按 doc_type 收集起来
#         parsed = {f: _as_str_or_none(data.get(f)) for f in ECMO_LLM_FIELDS}
#         evidence = {f: _as_str_or_none(evm.get(f)) for f in ECMO_LLM_FIELDS}
        
#         # ================== 【新增】：下机时间自动补全逻辑 ==================
#         off_time = parsed.get("ECMO下机记录时间")
#         if off_time:
#             import re
#             # 如果提取出的时间没有年份（没有 '20xx'，也没有 '年' 或 '-'）
#             if not re.search(r"20\d{2}|年|-|/", off_time):
#                 anchor = ctx.get("primary_anchor")
#                 if anchor:
#                     # anchor 形如 "2021-02-16 10:50:00"，截取前10位日期拼到前面
#                     date_part = str(anchor)[:10]
#                     parsed["ECMO下机记录时间"] = f"{date_part} {off_time}"
#         # ====================================================================
#         # 只要有一项有值，就存起来（为保持 json 干净，我们不存全量 ctx_text，只存 block_ids 溯源）
#         if any(v is not None for v in parsed.values()):
#             collected_data[doc_type].append({
#                 "data": parsed, 
#                 "evidence": evidence, 
#                 "block_ids": ctx.get("block_ids")
#             })

#     # 2. 交叉验证与合并逻辑
#     merged_data = {f: None for f in ECMO_LLM_FIELDS}
#     merged_ev = {f: None for f in ECMO_LLM_FIELDS}
    
#     success_flags_course = [item["data"]["是否ECMO脱机成功"] for item in collected_data["course"] if item["data"]["是否ECMO脱机成功"] in ["是", "否"]]
#     success_flags_big = [item["data"]["是否ECMO脱机成功"] for item in collected_data["big"] if item["data"]["是否ECMO脱机成功"] in ["是", "否"]]
    
#     all_flags = success_flags_course + success_flags_big
#     if "是" in all_flags and "否" not in all_flags:
#         merged_data["是否ECMO脱机成功"] = "是"
#     elif "否" in all_flags and "是" not in all_flags:
#         merged_data["是否ECMO脱机成功"] = "否"
#     elif "是" in all_flags and "否" in all_flags:
#         merged_data["是否ECMO脱机成功"] = "冲突(需人工核对)"


# # 【修改】：ECMO方式不需要全部拼接。优先提取明确的 V-A 或 V-V，兜底选最短的。
#     raw_modes = []
#     for dt in ["big", "course"]:
#         for item in collected_data[dt]:
#             v = item["data"].get("ECMO方式")
#             if v:
#                 raw_modes.append(v)
                
#     if raw_modes:
#         # 转换成大写拼在一起做正则/关键词探测
#         combined_text = " ".join(raw_modes).upper()
#         if "V-A" in combined_text or "VA " in combined_text or "VA-" in combined_text or "VAECMO" in combined_text:
#             merged_data["ECMO方式"] = "V-A"
#         elif "V-V" in combined_text or "VV " in combined_text or "VV-" in combined_text or "VVECMO" in combined_text:
#             merged_data["ECMO方式"] = "V-V"
#         else:
#             # 如果医生真没写 V-A/V-V，选一个长度最短的（大模型废话越少，通常越核心）
#             merged_data["ECMO方式"] = sorted(raw_modes, key=len)[0]
#     else:
#         merged_data["ECMO方式"] = None

# # 【修改】：ECMO下机记录时间 -> 单独去重，不加【病程录】前缀，保持干净格式
#     time_set = set()
#     for dt in ["big", "course"]:
#         for item in collected_data[dt]:
#             t = item["data"].get("ECMO下机记录时间")
#             if t:
#                 time_set.add(t)
#     merged_data["ECMO下机记录时间"] = " | ".join(time_set) if time_set else None

#     # ECMO下机记录内容 -> 仍保留前缀，方便医生溯源内容出处
#     for field in ["ECMO下机记录内容"]:
#         texts = []
#         evidences = []
#         seen_vals = set()
#         for doc_type in ["big", "course"]:
#             for item in collected_data[doc_type]:
#                 val = item["data"].get(field)
#                 if val and val not in seen_vals:
#                     seen_vals.add(val)
#                     prefix = "【大病历】" if doc_type == "big" else "【病程录】"
#                     texts.append(f"{prefix}{val}")
#                     evidences.append(f"{prefix}{item['evidence'].get(field, '')}")
        
#         if texts:
#             merged_data[field] = " | ".join(texts)
#             merged_ev[field] = " | ".join(evidences)

#     # ====== 3. 【新增】：将交叉验证中间状态彻底 Dump 落盘 ======
#     if dump_contexts_dir:
#         os.makedirs(dump_contexts_dir, exist_ok=True)
#         debug_path = os.path.join(dump_contexts_dir, "ecmo_cross_validation_debug.json")
#         debug_info = {
#             "1_raw_collections": collected_data,
#             "2_merged_decision": merged_data,
#             "3_is_conflict": merged_data["是否ECMO脱机成功"] == "冲突(需人工核对)"
#         }
#         with open(debug_path, "w", encoding="utf-8") as f:
#             json.dump(debug_info, f, ensure_ascii=False, indent=2)

#     return {
#         "data": merged_data,
#         "evidence_map": merged_ev,
#         "meta": meta,
#     }
from __future__ import annotations
import os
import json
from typing import Dict, Any, List, Optional
from .llm_ollama import ollama_generate, loads_json
from .prompts import ecmo_bundle_prompt
import re
from collections import Counter
from typing import Optional

def resolve_messy_times(raw_time_str: Optional[str]) -> Optional[str]:
    if not raw_time_str:
        return None
        
    # 1. 拆分成独立样本
    raw_list = [x.strip() for x in raw_time_str.split('|') if x.strip()]
    parsed_list = []
    
    for raw in raw_list:
        # 找年份 (20xx)
        year_m = re.search(r'(20\d{2})', raw)
        year = year_m.group(1) if year_m else None
        
        # 2. 基因提取：找月份和日期
        # 正则匹配形如 "03-05", "3月5日", "03/05"
        md_matches = re.findall(r'(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*[日]?', raw)
        month, day = None, None
        if md_matches:
            # 【神来之笔】：取最后一组匹配！完美破解 "2019-03-11 3月5日" 的融合怪
            month, day = md_matches[-1] 
            
        # 找时间（时分）
        hm_matches = re.search(r'(\d{1,2})\s*[:：时]\s*(\d{1,2})', raw)
        hour, minute = None, None
        if hm_matches:
            hour, minute = hm_matches.groups()
            
        # 3. 统一着装（标准化组装）
        if month and day:
            if not year: 
                year = "2020" # 终极兜底年份，实际业务中通常都有
            
            # 标准化日期：2019-03-05
            date_str = f"{year}-{int(month):02d}-{int(day):02d}"
            # 标准化时间：00:00:00
            time_str = f"{int(hour):02d}:{int(minute):02d}:00" if hour and minute else ""
            
            full_str = f"{date_str} {time_str}".strip()
            # 存入元组：(日期基准, 完整时间)
            parsed_list.append((date_str, full_str))
            
    if not parsed_list:
        return None
        
    # 4. 民主集中制：聚类与投票
    # 第一轮投票：选出共识日期 (排除掉诸如某一天记错的噪点)
    date_counts = Counter([x[0] for x in parsed_list])
    consensus_date = date_counts.most_common(1)[0][0] # 拿到票数最多的日期，如 '2019-03-05'
    
    # 第二轮筛选：在符合共识日期的候选项中，找精度最高的（字符串最长的）
    candidates = [x[1] for x in parsed_list if x[0] == consensus_date]
    candidates.sort(key=len, reverse=True)
    
    return candidates[0]
# 【修改】：加入了 ECMO上机时间，让大模型在操作记录缺失时充当备胎
ECMO_LLM_FIELDS = [
    "ECMO方式",
    "ECMO上机时间", 
    "ECMO下机记录时间",
    "ECMO下机记录内容",
    "是否ECMO脱机成功"
]

def _as_str_or_none(x: Any) -> Optional[str]:
    if x is None:
        return None
    if isinstance(x, str):
        s = x.strip()
        return s if s else None
    return str(x).strip() or None

def extract_ecmo_bundle(
    *,
    model: str,
    contexts: List[Dict[str, Any]],
    max_ctx: int = 50,
    dump_contexts_dir: Optional[str] = None,
) -> Dict[str, Any]:
    
    # 【修改】：收集容器加入了 "disch"
    collected_data = {"course": [], "big": [], "disch": []}
    meta = {"contexts_used": 0, "parse_errors": 0}

    # 1. 逐个 Context 调用 LLM
    for ctx in contexts[:max_ctx]:
        ctx_text = ctx.get("text", "")
        if not ctx_text:
            continue

        doc_type = ctx.get("doc_type")
        # 【修改】：允许解析出院记录
        if doc_type not in ["course", "big", "disch"]:
            continue

        prompt = ecmo_bundle_prompt(ctx_text)
        raw = ollama_generate(model, prompt, num_predict=8000)
        js = loads_json(raw)
        meta["contexts_used"] += 1
        
        if not isinstance(js, dict) or js.get("_parse_error"):
            meta["parse_errors"] += 1
            continue
            
        data = js.get("data")
        evm = js.get("evidence_map")
        if not isinstance(data, dict) or not isinstance(evm, dict):
            meta["parse_errors"] += 1
            continue

        parsed = {f: _as_str_or_none(data.get(f)) for f in ECMO_LLM_FIELDS}
        evidence = {f: _as_str_or_none(evm.get(f)) for f in ECMO_LLM_FIELDS}
        
        # 下机时间自动补全
        off_time = parsed.get("ECMO下机记录时间")
        if off_time:
            import re
            if not re.search(r"20\d{2}|年|-|/", off_time):
                anchor = ctx.get("primary_anchor")
                if anchor:
                    date_part = str(anchor)[:10]
                    parsed["ECMO下机记录时间"] = f"{date_part} {off_time}"
                    
        # 【新增】：上机时间自动补全
        on_time = parsed.get("ECMO上机时间")
        if on_time:
            import re
            if not re.search(r"20\d{2}|年|-|/", on_time):
                anchor = ctx.get("primary_anchor")
                if anchor:
                    date_part = str(anchor)[:10]
                    parsed["ECMO上机时间"] = f"{date_part} {on_time}"

        if any(v is not None for v in parsed.values()):
            collected_data[doc_type].append({
                "data": parsed, 
                "evidence": evidence, 
                "block_ids": ctx.get("block_ids")
            })

    # 2. 交叉验证与合并逻辑
    merged_data = {f: None for f in ECMO_LLM_FIELDS}
    merged_ev = {f: None for f in ECMO_LLM_FIELDS}
    
    # 增加 disch 投票
    success_flags_course = [item["data"]["是否ECMO脱机成功"] for item in collected_data["course"] if item["data"]["是否ECMO脱机成功"] in ["是", "否"]]
    success_flags_big = [item["data"]["是否ECMO脱机成功"] for item in collected_data["big"] if item["data"]["是否ECMO脱机成功"] in ["是", "否"]]
    success_flags_disch = [item["data"]["是否ECMO脱机成功"] for item in collected_data["disch"] if item["data"]["是否ECMO脱机成功"] in ["是", "否"]]
    
    all_flags = success_flags_course + success_flags_big + success_flags_disch
    if "是" in all_flags and "否" not in all_flags:
        merged_data["是否ECMO脱机成功"] = "是"
    elif "否" in all_flags and "是" not in all_flags:
        merged_data["是否ECMO脱机成功"] = "否"
    elif "是" in all_flags and "否" in all_flags:
        merged_data["是否ECMO脱机成功"] = "冲突(需人工核对)"

    # ================== 【新增：ECMO上机时间提取与排序】 ==================
    on_times = []
    on_evidences = {}
    for dt in ["big", "course", "disch"]:
        for item in collected_data[dt]:
            t = item["data"].get("ECMO上机时间")
            ev = item["evidence"].get("ECMO上机时间")
            if t:
                import re
                # 规范格式以供排序
                sortable_t = re.sub(r"[年月/.]", "-", t).replace("日", " ").strip()
                if len(sortable_t) == 10:
                    sortable_t += " 23:59:59"
                on_times.append((sortable_t, t))
                prefix = "【大病历】" if dt == "big" else ("【病程录】" if dt == "course" else "【出院记录】")
                on_evidences[t] = f"{prefix}{ev}"
                
    if on_times:
        # 取时间最早的
        on_times.sort(key=lambda x: x[0])
        earliest_raw_time = on_times[0][1]
        merged_data["ECMO上机时间"] = earliest_raw_time
        merged_ev["ECMO上机时间"] = on_evidences[earliest_raw_time]
    # ====================================================================

    # ECMO方式
    raw_modes = []
    for dt in ["big", "course", "disch"]:
        for item in collected_data[dt]:
            v = item["data"].get("ECMO方式")
            if v:
                raw_modes.append(v)
                
    if raw_modes:
        combined_text = " ".join(raw_modes).upper()
        if "V-A" in combined_text or "VA " in combined_text or "VA-" in combined_text or "VAECMO" in combined_text:
            merged_data["ECMO方式"] = "V-A"
        elif "V-V" in combined_text or "VV " in combined_text or "VV-" in combined_text or "VVECMO" in combined_text:
            merged_data["ECMO方式"] = "V-V"
        else:
            merged_data["ECMO方式"] = sorted(raw_modes, key=len)[0]
    else:
        merged_data["ECMO方式"] = None

    # ECMO下机记录时间
    time_set = set()
    for dt in ["big", "course", "disch"]:
        for item in collected_data[dt]:
            t = item["data"].get("ECMO下机记录时间")
            if t:
                time_set.add(t)
    merged_data["ECMO下机记录时间"] = " | ".join(time_set) if time_set else None

    # ECMO下机记录内容
    for field in ["ECMO下机记录内容"]:
        texts = []
        evidences = []
        seen_vals = set()
        for doc_type in ["big", "course", "disch"]:
            for item in collected_data[doc_type]:
                val = item["data"].get(field)
                if val and val not in seen_vals:
                    seen_vals.add(val)
                    prefix = "【大病历】" if doc_type == "big" else ("【病程录】" if doc_type == "course" else "【出院记录】")
                    texts.append(f"{prefix}{val}")
                    evidences.append(f"{prefix}{item['evidence'].get(field, '')}")
        
        if texts:
            merged_data[field] = " | ".join(texts)
            merged_ev[field] = " | ".join(evidences)

    if dump_contexts_dir:
        os.makedirs(dump_contexts_dir, exist_ok=True)
        debug_path = os.path.join(dump_contexts_dir, "ecmo_cross_validation_debug.json")
        debug_info = {
            "1_raw_collections": collected_data,
            "2_merged_decision": merged_data,
            "3_is_conflict": merged_data["是否ECMO脱机成功"] == "冲突(需人工核对)",
            "raw_contexts": contexts
        }
        with open(debug_path, "w", encoding="utf-8") as f:
            json.dump(debug_info, f, ensure_ascii=False, indent=2)

    return {
        "data": merged_data,
        "evidence_map": merged_ev,
        "meta": meta,
    }
# import os
# import json
# import re
# from typing import Dict, Any, List, Optional
# from collections import Counter
# from .llm_ollama import ollama_generate, loads_json
# from .prompts import ecmo_bundle_prompt

# # 【辅助函数】：专门处理格式混乱的时间融合怪
# def resolve_messy_times(raw_time_str: Optional[str]) -> Optional[str]:
#     if not raw_time_str:
#         return None
        
#     # 1. 拆分成独立样本
#     raw_list = [x.strip() for x in raw_time_str.split('|') if x.strip()]
#     parsed_list = []
    
#     for raw in raw_list:
#         # 找年份 (20xx)
#         year_m = re.search(r'(20\d{2})', raw)
#         year = year_m.group(1) if year_m else None
        
#         # 2. 基因提取：找月份和日期
#         # 正则匹配形如 "03-05", "3月5日", "03/05"
#         md_matches = re.findall(r'(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*[日]?', raw)
#         month, day = None, None
#         if md_matches:
#             # 【核心机制】：取最后一组匹配！完美破解 "2019-03-11 3月5日" 的融合怪
#             month, day = md_matches[-1] 
            
#         # 找时间（时分）
#         hm_matches = re.search(r'(\d{1,2})\s*[:：时]\s*(\d{1,2})', raw)
#         hour, minute = None, None
#         if hm_matches:
#             hour, minute = hm_matches.groups()
            
#         # 3. 统一着装（标准化组装）
#         if month and day:
#             if not year: 
#                 year = "2020" # 终极兜底年份，实际业务中通常都有
            
#             # 标准化日期：2019-03-05
#             date_str = f"{year}-{int(month):02d}-{int(day):02d}"
#             # 标准化时间：00:00:00
#             time_str = f"{int(hour):02d}:{int(minute):02d}:00" if hour and minute else ""
            
#             full_str = f"{date_str} {time_str}".strip()
#             # 存入元组：(日期基准, 完整时间)
#             parsed_list.append((date_str, full_str))
            
#     if not parsed_list:
#         return None
        
#     # 4. 民主集中制：聚类与投票
#     # 第一轮投票：选出共识日期 (排除掉诸如某一天记错的噪点)
#     date_counts = Counter([x[0] for x in parsed_list])
#     consensus_date = date_counts.most_common(1)[0][0] # 拿到票数最多的日期，如 '2019-03-05'
    
#     # 第二轮筛选：在符合共识日期的候选项中，找精度最高的（字符串最长的）
#     candidates = [x[1] for x in parsed_list if x[0] == consensus_date]
#     candidates.sort(key=len, reverse=True)
    
#     return candidates[0]

# # =======================================================================================

# # ECMO 字段列表
# ECMO_LLM_FIELDS = [
#     "ECMO方式",
#     "ECMO上机时间", 
#     "ECMO下机记录时间",
#     "ECMO下机记录内容",
#     "是否ECMO脱机成功"
# ]

# def _as_str_or_none(x: Any) -> Optional[str]:
#     if x is None:
#         return None
#     if isinstance(x, str):
#         s = x.strip()
#         return s if s else None
#     return str(x).strip() or None

# def extract_ecmo_bundle(
#     *,
#     model: str,
#     contexts: List[Dict[str, Any]],
#     max_ctx: int = 15,
#     dump_contexts_dir: Optional[str] = None,
# ) -> Dict[str, Any]:
    
#     collected_data = {"course": [], "big": [], "disch": []}
#     meta = {"contexts_used": 0, "parse_errors": 0}

#     # ==========================================================
#     # 第一阶段：逐个 Context 调用 LLM 并补全日期
#     # ==========================================================
#     for ctx in contexts[:max_ctx]:
#         ctx_text = ctx.get("text", "")
#         if not ctx_text:
#             continue

#         doc_type = ctx.get("doc_type")
#         if doc_type not in ["course", "big", "disch"]:
#             continue

#         prompt = ecmo_bundle_prompt(ctx_text)
#         raw = ollama_generate(model, prompt, num_predict=8000)
#         js = loads_json(raw)
#         meta["contexts_used"] += 1
        
#         if not isinstance(js, dict) or js.get("_parse_error"):
#             meta["parse_errors"] += 1
#             continue
            
#         data = js.get("data")
#         evm = js.get("evidence_map")
#         if not isinstance(data, dict) or not isinstance(evm, dict):
#             meta["parse_errors"] += 1
#             continue

#         parsed = {f: _as_str_or_none(data.get(f)) for f in ECMO_LLM_FIELDS}
#         evidence = {f: _as_str_or_none(evm.get(f)) for f in ECMO_LLM_FIELDS}
        
#         # --- 下机时间自动补全 ---
#         off_time = parsed.get("ECMO下机记录时间")
#         if off_time:
#             if not re.search(r"20\d{2}|年|-|/", off_time):
#                 anchor = ctx.get("primary_anchor")
#                 if anchor:
#                     date_part = str(anchor)[:10]
#                     parsed["ECMO下机记录时间"] = f"{date_part} {off_time}"
                    
#         # --- 上机时间自动补全 ---
#         on_time = parsed.get("ECMO上机时间")
#         if on_time:
#             if not re.search(r"20\d{2}|年|-|/", on_time):
#                 anchor = ctx.get("primary_anchor")
#                 if anchor:
#                     date_part = str(anchor)[:10]
#                     parsed["ECMO上机时间"] = f"{date_part} {on_time}"

#         # 只要有一项有值，就存起来（注意这里的缩进，它在 if on_time 外面，与 for 循环内部平齐）
#         if any(v is not None for v in parsed.values()):
#             collected_data[doc_type].append({
#                 "data": parsed, 
#                 "evidence": evidence, 
#                 "block_ids": ctx.get("block_ids")
#             })

#     # ==========================================================
#     # 第二阶段：交叉验证、排序与合并逻辑 (The Global Voter)
#     # ==========================================================
#     merged_data = {f: None for f in ECMO_LLM_FIELDS}
#     merged_ev = {f: None for f in ECMO_LLM_FIELDS}
    
#     # 1. 是否脱机成功 (投票制)
#     success_flags_course = [item["data"]["是否ECMO脱机成功"] for item in collected_data["course"] if item["data"]["是否ECMO脱机成功"] in ["是", "否"]]
#     success_flags_big = [item["data"]["是否ECMO脱机成功"] for item in collected_data["big"] if item["data"]["是否ECMO脱机成功"] in ["是", "否"]]
#     success_flags_disch = [item["data"]["是否ECMO脱机成功"] for item in collected_data["disch"] if item["data"]["是否ECMO脱机成功"] in ["是", "否"]]
    
#     all_flags = success_flags_course + success_flags_big + success_flags_disch
#     if "是" in all_flags and "否" not in all_flags:
#         merged_data["是否ECMO脱机成功"] = "是"
#     elif "否" in all_flags and "是" not in all_flags:
#         merged_data["是否ECMO脱机成功"] = "否"
#     elif "是" in all_flags and "否" in all_flags:
#         merged_data["是否ECMO脱机成功"] = "冲突(需人工核对)"

#     # 2. ECMO上机时间 (取最早的时间)
#     on_times = []
#     on_evidences = {}
#     for dt in ["big", "course", "disch"]:
#         for item in collected_data[dt]:
#             t = item["data"].get("ECMO上机时间")
#             ev = item["evidence"].get("ECMO上机时间")
#             if t:
#                 # 规范格式以供排序
#                 sortable_t = re.sub(r"[年月/.]", "-", t).replace("日", " ").strip()
#                 if len(sortable_t) == 10:
#                     sortable_t += " 23:59:59"
#                 on_times.append((sortable_t, t))
#                 prefix = "【大病历】" if dt == "big" else ("【病程录】" if dt == "course" else "【出院记录】")
#                 on_evidences[t] = f"{prefix}{ev}"
                
#     if on_times:
#         on_times.sort(key=lambda x: x[0])
#         earliest_raw_time = on_times[0][1]
#         merged_data["ECMO上机时间"] = earliest_raw_time
#         merged_ev["ECMO上机时间"] = on_evidences[earliest_raw_time]

#     # 3. ECMO方式 (短特征提取)
#     raw_modes = []
#     for dt in ["big", "course", "disch"]:
#         for item in collected_data[dt]:
#             v = item["data"].get("ECMO方式")
#             if v:
#                 raw_modes.append(v)
                
#     if raw_modes:
#         combined_text = " ".join(raw_modes).upper()
#         if "V-A" in combined_text or "VA " in combined_text or "VA-" in combined_text or "VAECMO" in combined_text:
#             merged_data["ECMO方式"] = "V-A"
#         elif "V-V" in combined_text or "VV " in combined_text or "VV-" in combined_text or "VVECMO" in combined_text:
#             merged_data["ECMO方式"] = "V-V"
#         else:
#             merged_data["ECMO方式"] = sorted(raw_modes, key=len)[0]

#     # ================== 4. 重点：ECMO下机记录时间的时序消解 ==================
#     raw_off_events = []
#     for dt in ["big", "course", "disch"]:
#         for item in collected_data[dt]:
#             t = item["data"].get("ECMO下机记录时间")
#             ev = item["evidence"].get("ECMO下机记录时间")
#             content = item["data"].get("ECMO下机记录内容")
#             if t:
#                 raw_off_events.append({
#                     "time": t, 
#                     "ev": ev, 
#                     "content": content,
#                     "doc_type": dt
#                 })

#     if raw_off_events:
#         # 第一步：把所有碎片抽出来，送进清洗机
#         time_fragments = set([e["time"] for e in raw_off_events])
#         raw_combined_str = " | ".join(time_fragments)
#         final_clean_time = resolve_messy_times(raw_combined_str)
        
#         merged_data["ECMO下机记录时间"] = final_clean_time
        
#         # 第二步：寻找与这个最终清洗时间最匹配的原始内容，作为我们的最终输出
#         # （因为我们洗过一次，所以要反向找回它属于哪个事件）
#         best_event = None
#         if final_clean_time:
#             # 取 final_clean_time 的前 10 位作为查找基准，比如 "2019-03-05"
#             base_date = final_clean_time[:10] 
#             for event in raw_off_events:
#                 # 只要原始事件的时间里包含了这个基准日期（或者对应的中文日期），就认定是它
#                 clean_e_time = re.sub(r"[年月/.]", "-", event["time"]).replace("日", " ")
#                 if base_date in clean_e_time or (str(int(base_date[5:7]))+"-" in clean_e_time):
#                     best_event = event
#                     break
        
#         if not best_event:
#             # 兜底：如果反向查找失败，至少取第一个事件的内容
#             best_event = raw_off_events[0]
            
#         prefix = "【大病历】" if best_event["doc_type"] == "big" else ("【病程录】" if best_event["doc_type"] == "course" else "【出院记录】")
        
#         if best_event["content"]:
#             merged_data["ECMO下机记录内容"] = f"{prefix}{best_event['content']}"
#             merged_ev["ECMO下机记录内容"] = f"{prefix}{best_event['ev']}"
#         else:
#             merged_data["ECMO下机记录内容"] = None
#     # =========================================================================

#     # 3. 写入 Debug 记录
#     if dump_contexts_dir:
#         os.makedirs(dump_contexts_dir, exist_ok=True)
#         debug_path = os.path.join(dump_contexts_dir, "ecmo_cross_validation_debug.json")
#         debug_info = {
#             "1_raw_collections": collected_data,
#             "2_merged_decision": merged_data,
#             "3_is_conflict": merged_data["是否ECMO脱机成功"] == "冲突(需人工核对)"
#         }
#         with open(debug_path, "w", encoding="utf-8") as f:
#             json.dump(debug_info, f, ensure_ascii=False, indent=2)

#     return {
#         "data": merged_data,
#         "evidence_map": merged_ev,
#         "meta": meta,
#     }