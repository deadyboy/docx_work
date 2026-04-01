"""Extraction router.

You asked about a "router/rooter" module. In this project, routing logic was
previously embedded in pipeline_patient.py / pipeline_demo.py.

This file makes that routing explicit and extensible:
- Choose a recall strategy per field
- Choose a prompt/extractor per field (lab_prompt vs time_sensitive_prompt, etc.)

For now, it routes "lab-style" fields (e.g., PCT/CRP) using extract_lab_items.
"""

from __future__ import annotations
import os
from .debug_dump import dump_contexts
import re
from typing import Dict, Any, List, Optional
from .recall import recall_patient

from .field_config import LAB_FIELD_SPECS, LabFieldSpec, PANEL_FIELD_SPECS, PanelFieldSpec
from .extract_lab import extract_lab_items
from .extract_lab import extract_score_items  # 如果你已有
from .extract_panel import extract_panel_items  # 新增
from .field_config import FLAGS_DEFAULT_SPEC, FlagsFieldSpec
from .extract_flag import extract_flags_items
from .field_config import ECMO_BUNDLE_SPEC, BundleFieldSpec
# from .extract_ecmo import extract_ecmo_bundle
from .extract_base import extract_patient_base_bundle
# router.py（替换/改造）


def _filter_contexts(contexts, include_patterns=None, exclude_patterns=None):
    if not include_patterns and not exclude_patterns:
        return contexts
    inc = [re.compile(p, re.IGNORECASE) for p in (include_patterns or [])]
    exc = [re.compile(p, re.IGNORECASE) for p in (exclude_patterns or [])]
    out = []
    for c in contexts:
        t = c.get("text", "")
        if exc and any(p.search(t) for p in exc):
            continue
        if inc and (not any(p.search(t) for p in inc)):
            continue
        out.append(c)
    return out







def extract_lab_field(
    *,
    model: str,
    docs: Dict[str, Any],
    spec: LabFieldSpec,
    dump_contexts_dir: Optional[str] = None,
) -> Dict[str, Any]:

    contexts = recall_patient(
        docs,
        aliases=spec.aliases,
        k_course=spec.k_course,
        k_free=spec.k_free,
    )

    # 可选：dump 每个字段的 contexts
    if dump_contexts_dir:
        os.makedirs(dump_contexts_dir, exist_ok=True)
        dump_contexts(contexts, os.path.join(dump_contexts_dir, f"contexts_{spec.key}.txt"))

    if spec.extractor == "score":
        return extract_score_items(
            model=model,
            score_name=spec.lab_name,
            aliases=spec.aliases,
            unit_candidates=spec.unit_candidates, 
            contexts=contexts,
            max_items=50,
        )

    # 默认 lab
    return extract_lab_items(
        model=model,
        lab_name=spec.lab_name,
        aliases=spec.aliases,
        unit_candidates=spec.unit_candidates,
        contexts=contexts,
        max_items=50,
    )





def extract_panel_field(
    *,
    model: str,
    docs: Dict[str, Any],
    spec: PanelFieldSpec,
    dump_contexts_dir: Optional[str] = None,
) -> Dict[str, Any]:

    # recall：用 triggers + 所有 analyte aliases 一起召回（保证覆盖）
    recall_aliases = list(spec.triggers)
    for a in spec.analytes:
        recall_aliases.extend(a.aliases)

    contexts = recall_patient(
        docs,
        aliases=recall_aliases,
        k_course=spec.k_course,
        k_free=spec.k_free,
    )

    if dump_contexts_dir:
        import os
        from .debug_dump import dump_contexts
        os.makedirs(dump_contexts_dir, exist_ok=True)
        dump_contexts(contexts, os.path.join(dump_contexts_dir, f"contexts_{spec.key}.txt"))

    analytes_payload = [
        {"key": a.key, "aliases": a.aliases, "unit_candidates": a.unit_candidates}
        for a in spec.analytes
    ]

    return extract_panel_items(
        model=model,
        panel_name=spec.panel_name,
        triggers=spec.triggers,
        analytes=analytes_payload,
        min_present=spec.min_present,
        contexts=contexts,
        max_items=50,
    )








def extract_flags_field(
    *,
    model: str,
    docs: Dict[str, Any],
    spec: FlagsFieldSpec,
    dump_contexts_dir: Optional[str] = None,
) -> Dict[str, Any]:

    # 分域模式：每个 domain 单独召回 + 单独抽取
    if spec.domains:
        merged_data: Dict[str, Any] = {}
        merged_evm: Dict[str, str] = {}
        merged_src: Dict[str, Any] = {}
        meta = {"domains": {}, "parse_errors": 0}

        for d in spec.domains:
            # 1) 仅保留该域相关 doc_types
            sub_docs = {dt: docs[dt] for dt in d.doc_types if dt in docs}

            # 2) recall
            contexts = recall_patient(
                sub_docs,
                aliases=d.aliases,
                k_course=d.k_course,
                k_free=d.k_free,
            )

            # 3) domain-level include/exclude 过滤
            contexts = _filter_contexts(
                contexts,
                include_patterns=d.include_patterns,
                exclude_patterns=d.exclude_patterns,
            )

            # 4) dump contexts（每域一个文件，便于你人工验证“证据域是否正确”）
            if dump_contexts_dir:
                os.makedirs(dump_contexts_dir, exist_ok=True)
                dump_contexts(
                    contexts,
                    os.path.join(dump_contexts_dir, f"contexts_FLAGS_{d.name}.txt")
                )

            # 5) extract（该域只负责它的字段集合）
            out = extract_flags_items(
                model=model,
                contexts=contexts,
                fields=d.fields,
                domain=d.name,
                max_ctx=d.max_ctx,
                stop_ratio=d.stop_ratio,
            )

            data = out.get("data", {}) if isinstance(out, dict) else {}
            evm = out.get("evidence_map", {}) if isinstance(out, dict) else {}
            src = out.get("source_map", {}) if isinstance(out, dict) else {}
            m = out.get("meta", {}) if isinstance(out, dict) else {}

            meta["domains"][d.name] = {
                "contexts": len(contexts),
                "contexts_used": m.get("contexts_used"),
                "parse_errors": m.get("parse_errors", 0),
            }
            meta["parse_errors"] += m.get("parse_errors", 0) or 0

            # 6) 合并：由于各域字段互斥，直接写入即可
            for k, v in data.items():
                if v is None:
                    continue
                merged_data[k] = v
                if k in evm:
                    merged_evm[k] = evm[k]
                if k in src:
                    merged_src[k] = src[k]

        # 计算 FLAGS 全字段集合（来自所有 domain.fields）
        all_fields = []
        for d in spec.domains:
            all_fields.extend([name for name, _ in d.fields])

        # 用全集补齐 None
        final_data = {k: merged_data.get(k, None) for k in all_fields}

        # evidence/source 也可以只保留有值者（或同样补齐为空字符串）
        return {
            "data": final_data,
            "evidence_map": merged_evm,
            "source_map": merged_src,
            "meta": meta,
        }
    # 兼容旧模式：不分域
    contexts = recall_patient(
        docs,
        aliases=spec.aliases,
        k_course=spec.k_course,
        k_free=spec.k_free,
    )
    if dump_contexts_dir:
        os.makedirs(dump_contexts_dir, exist_ok=True)
        dump_contexts(contexts, os.path.join(dump_contexts_dir, "contexts_FLAGS.txt"))

    return extract_flags_items(
        model=model,
        contexts=contexts,
        fields=spec.fields,
        domain=spec.name,
        max_ctx=spec.max_ctx,
        stop_ratio=spec.stop_ratio,
    )








# def extract_ecmo_field(
#     *,
#     model: str,
#     docs: Dict[str, Any],
#     spec: BundleFieldSpec,
#     dump_contexts_dir: Optional[str] = None,
# ) -> Dict[str, Any]:
#     contexts = recall_patient(
#         docs,
#         aliases=spec.aliases,
#         k_course=spec.k_course,
#         k_free=spec.k_free,
#     )

#     # M3：router 统一 dump
#     if dump_contexts_dir:
#         os.makedirs(dump_contexts_dir, exist_ok=True)
#         dump_contexts(contexts, os.path.join(dump_contexts_dir, f"contexts_{spec.key}.txt"))

#     return extract_ecmo_bundle(
#         model=model,
#         contexts=contexts,
#         max_ctx=12,
#         # 不再传 dump_contexts_dir
#     )

#def extract_ecmo_field(
#     *,
#     model: str,
#     docs: Dict[str, Any],
#     spec: BundleFieldSpec,
#     dump_contexts_dir: Optional[str] = None,
# ) -> Dict[str, Any]:
    
#     # === 1. Python 规则拦截：从“操作记录(op)”提取上机信息 ===
#     op_blocks = docs.get("op", [])
#     op_text = "\n".join(b.text for b in op_blocks)
    
#     op_time = None
#     op_content = None
#     op_mode = None  # 【新增】：用来存从操作记录标题里抓到的 ECMO 方式
    
#     # 如果操作记录中包含 ECMO 关键词
#     if any(k.lower() in op_text.lower() for k in ["ecmo", "体外膜肺", "v-a", "v-v", "va-", "vv-"]):
#         op_content = op_text
        
#         # 提取时间
#         # ================== 【修改核心逻辑：锚点截取操作时间】 ==================
#         # 直接寻找“操作时间：”字样，截取这一整行的内容，直到换行符结束
#         time_match = re.search(r"操作时间\s*[:：]\s*([^\n]+)", op_text[:1000])
        
#         if time_match:
#             # 拿到整行文本后，剔除里面可能存在的所有空格，得到最紧凑的时间字符串
#             op_time = re.sub(r"\s+", "", time_match.group(1))
#         else:
#             # 兜底：万一有些没素质的医生没写“操作时间：”这几个字，再用正则硬抓第一串日期
#             # 这里我顺手把“时/分”也加进正则里了，以防万一
#             fallback_match = re.search(r"(20\d{2}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}\s*[日]?\s*(?:\d{1,2}\s*[:：时]\s*\d{1,2}\s*[分]?)?)", op_text[:1000])
#             if fallback_match:
#                 op_time = re.sub(r"\s+", "", fallback_match.group(1))
#         # =====================================================================

#         # ================== 【新增核心逻辑：标题截获 ECMO 方式】 ==================
#         # 取操作记录的前 200 个字符（通常包含标题“操作名称：VA-ECMO留置记录”）
#         op_header = op_text[:200].upper()
#         if "V-A" in op_header or "VA-" in op_header or "VA ECMO" in op_header or "VAECMO" in op_header:
#             op_mode = "V-A"
#         elif "V-V" in op_header or "VV-" in op_header or "VV ECMO" in op_header or "VVECMO" in op_header:
#             op_mode = "V-V"
#         # =========================================================================

#     # === 2. 限制召回域：只让大模型看大病历(big)和病程录(course) ===
#     sub_docs = {dt: docs[dt] for dt in ["big", "course"] if dt in docs}
#     contexts = recall_patient(
#         sub_docs,
#         aliases=spec.aliases,
#         k_course=spec.k_course,
#         k_free=spec.k_free,
#     )

#     if dump_contexts_dir:
#         os.makedirs(dump_contexts_dir, exist_ok=True)
#         # dump_contexts(contexts, os.path.join(dump_contexts_dir, f"contexts_{spec.key}.txt"))

#     # === 3. 调用大模型提取脱机信息 ===
#     llm_result = extract_ecmo_bundle(
#         model=model,
#         contexts=contexts,
#         max_ctx=12,
#         dump_contexts_dir=dump_contexts_dir
#     )

#     # === 4. 合并 Python 提取的结果与大模型结果 ===
#     data = llm_result.get("data", {})
#     evm = llm_result.get("evidence_map", {})
    
#     # 回填上机时间和全文
#     data["ECMO上机时间"] = op_time
#     data["ECMO机器记录内容"] = op_content
#     evm["ECMO上机时间"] = "【系统规则自动提取自操作记录】" if op_time else None
#     evm["ECMO机器记录内容"] = "【系统规则自动提取自操作记录全文】" if op_content else None

#     # ================== 【新增：最高优先级覆写】 ==================
#     # 如果我们在操作记录的标题里抓到了 V-A 或 V-V，直接一票否决大模型的乱猜！
#     # （保留大模型在 extract_ecmo_bundle 里的提取仅作为某些病人没有操作记录时的兜底）
#     if op_mode:
#         data["ECMO方式"] = op_mode
#         evm["ECMO方式"] = f"【系统规则自动提取自操作记录标题】"
#     # ==============================================================

#     llm_result["data"] = data
#     llm_result["evidence_map"] = evm
    
#     return llm_result

# def extract_ecmo_field(
#     *,
#     model: str,
#     docs: Dict[str, Any],
#     spec: BundleFieldSpec,
#     dump_contexts_dir: Optional[str] = None,
# ) -> Dict[str, Any]:
    
#     # === 1. Python 规则拦截：从“操作记录(op)”提取上机信息 ===
#     op_blocks = docs.get("op", [])
#     op_text = "\n".join(b.text for b in op_blocks)
    
#     op_time = None
#     op_content = None
#     op_mode = None  # 用来存从操作记录标题里抓到的 ECMO 方式
    
#     # 如果操作记录中包含 ECMO 关键词
#     if any(k.lower() in op_text.lower() for k in ["ecmo", "体外膜肺", "v-a", "v-v", "va-", "vv-"]):
#         op_content = op_text
        
#         # 提取时间
#         # ================== 【修改核心逻辑：锚点截取与有效性校验】 ==================
#         time_match = re.search(r"操作时间\s*[:：]\s*([^\n]+)", op_text[:1000])
        
#         if time_match:
#             raw_t = time_match.group(1).strip()
#             # 校验：如果医生只写了“年 月 日”这种空模板，连4个数字（年份）都没有，视为无效
#             if len(re.findall(r"\d", raw_t)) >= 4:
#                 op_time = re.sub(r"\s+", "", raw_t)
#         else:
#             # 兜底正则
#             fallback_match = re.search(r"(20\d{2}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}\s*[日]?\s*(?:\d{1,2}\s*[:：时]\s*\d{1,2}\s*[分]?)?)", op_text[:1000])
#             if fallback_match:
#                 op_time = re.sub(r"\s+", "", fallback_match.group(1))
#         # =====================================================================

#         # ================== 【核心逻辑：标题截获 ECMO 方式】 ==================
#         op_header = op_text[:200].upper()
#         if "V-A" in op_header or "VA-" in op_header or "VA ECMO" in op_header or "VAECMO" in op_header:
#             op_mode = "V-A"
#         elif "V-V" in op_header or "VV-" in op_header or "VV ECMO" in op_header or "VVECMO" in op_header:
#             op_mode = "V-V"
#         # =========================================================================

#     # === 2. 限制召回域：【新增】将出院记录(disch)加入搜索范围 ===
#     sub_docs = {dt: docs[dt] for dt in ["big", "course", "disch"] if dt in docs}
#     contexts = recall_patient(
#         sub_docs,
#         aliases=spec.aliases,
#         k_course=spec.k_course,
#         k_free=spec.k_free,
#     )

#     # ================== 【新增：上下文优先级排序】 ==================
#     # 解决“ECMO日常记录太多，导致真正下机记录被 max_ctx 截断排挤”的问题
#     def _score_ecmo_ctx(ctx) -> int:
#         txt = ctx.get("text", "")
#         score = 0
#         # 优先级1：脱机/下机事件（最关键信息，权重最高）
#         if any(kw in txt for kw in ["撤机", "脱机", "拔除", "撤除", "停用", "下机"]):
#             score += 100
#         # 优先级2：上机/建立事件（作为操作记录缺失时的补充）
#         if any(kw in txt for kw in ["上机", "置入", "建立", "留置", "启动"]):
#             score += 50
#         # 优先级3：明确提及了模式
#         if any(kw in txt for kw in ["V-A", "V-V", "VA-", "VV-"]):
#             score += 20
#         # 其他日常带机记录得分为 0
#         return score

#     # 将 80 多个 contexts 按重要性降序排列
#     contexts.sort(key=_score_ecmo_ctx, reverse=True)
#     # ==============================================================

#     if dump_contexts_dir:
#         os.makedirs(dump_contexts_dir, exist_ok=True)
#         # 此时 dump 出来的 contexts 就是按优先级排好序的，你可以去文件里验证
#         # dump_contexts(contexts, os.path.join(dump_contexts_dir, f"contexts_{spec.key}.txt"))

#     # === 3. 调用大模型提取脱机与兜底信息 ===
#     # 此时切片的 [:max_ctx] 拿到的绝对是排在前面的高分片段（即脱机和上机片段）
#     llm_result = extract_ecmo_bundle(
#         model=model,
#         contexts=contexts,
#         max_ctx=15,  # 【修改】：适当增加 max_ctx，确保脱机记录被覆盖到
#         dump_contexts_dir=dump_contexts_dir
#     )

#     # === 4. 合并 Python 提取的结果与大模型结果 ===
#     data = llm_result.get("data", {})
#     evm = llm_result.get("evidence_map", {})
    
#     # 回填操作全文
#     data["ECMO机器记录内容"] = op_content
#     evm["ECMO机器记录内容"] = "【系统规则自动提取自操作记录全文】" if op_content else None

#     # ================== 【新增：按优先级回填上机时间】 ==================
#     if op_time:
#         data["ECMO上机时间"] = op_time
#         evm["ECMO上机时间"] = "【系统规则自动提取自操作记录】"
#     # 若 op_time 校验失败为空，则原样保留 LLM 在 extract_ecmo_bundle 抓到的时间
#     # ==============================================================

#     # 最高优先级覆写方式
#     if op_mode:
#         data["ECMO方式"] = op_mode
#         evm["ECMO方式"] = f"【系统规则自动提取自操作记录标题】"

#     llm_result["data"] = data
#     llm_result["evidence_map"] = evm
    
#     return llm_result


# 导入你的新模块
# from .extract_ecmo_events import extract_ecmo_events
# from .ecmo_episode_builder import build_ecmo_episodes, build_ecmo_fields
# from .recall import recall_patient # 确保召回函数存在
# def extract_ecmo_field(
#     *,
#     model: str,
#     docs: Dict[str, Any],
#     spec: BundleFieldSpec, # 你的 BundleFieldSpec
#     dump_contexts_dir: Optional[str] = None,
# ) -> Dict[str, Any]:
    
#     # 1. 保留最可靠的 Python 操作记录强拦截（因为结构化数据永远最准）
#     op_blocks = docs.get("op", [])
#     op_text = "\n".join(b.text for b in op_blocks)
#     op_time, op_content, op_mode = None, None, None
    
#     if any(k.lower() in op_text.lower() for k in ["ecmo", "v-a", "v-v"]):
#         op_content = op_text
#         import re
#         time_match = re.search(r"操作时间\s*[:：]\s*([^\n]+)", op_text[:1000])
#         if time_match and len(re.findall(r"\d", time_match.group(1))) >= 4:
#             op_time = re.sub(r"\s+", "", time_match.group(1))
        
#         op_header = op_text[:200].upper()
#         if "V-A" in op_header or "VA-" in op_header: op_mode = "V-A"
#         elif "V-V" in op_header or "VV-" in op_header: op_mode = "V-V"

#     # 2. 召回并排序上下文
#     sub_docs = {dt: docs[dt] for dt in ["big", "course", "disch"] if dt in docs}
#     print(f"\n[DEBUG 探针] 原始配置传入的 k_course={spec.k_course}, k_free={spec.k_free}")
    
#     contexts = recall_patient(
#         sub_docs,
#         aliases=spec.aliases,
#         k_course=0, # 强行拦截！
#         k_free=0,   # 强行拦截！
#     )
    
#     # 再次增加探针，强行检查召回出来的碎片到底有多大！
#     for i, ctx in enumerate(contexts):
#         blocks = ctx.get("block_ids", [])
#         print(f"CTX#{i} 包含了 {len(blocks)} 个 blocks")
    
#     # 将高价值动作词所在段落排在前面
#     def _score_ctx(ctx):
#         txt = ctx.get("text", "")
#         score = 0
#         if any(kw in txt for kw in ["撤机", "脱机", "拔除", "停止", "上机", "建立"]): score += 100
#         return score
#     contexts.sort(key=_score_ctx, reverse=True)

#     # 3. 【全新引擎介入】：提取事件 -> 构建 Episode -> 生成字段
#     raw_events = extract_ecmo_events(model=model, contexts=contexts, max_ctx=50)
#     episodes, llm_mode = build_ecmo_episodes(raw_events)
#     final_result = build_ecmo_fields(episodes, llm_mode)
    
#     data = final_result["data"]
#     evm = final_result["evidence_map"]

#     # 4. 操作单最高优先级覆写
#     data["ECMO机器记录内容"] = op_content
#     evm["ECMO机器记录内容"] = "【操作记录全文】" if op_content else None
    
#     if op_time:
#         data["ECMO上机时间"] = op_time
#         evm["ECMO上机时间"] = "【系统规则自动提取自操作记录】"
#     if op_mode:
#         data["ECMO方式"] = op_mode
#         evm["ECMO方式"] = "【系统规则自动提取自操作记录标题】"

#     # DEBUG 输出：把你刚才说的内部逻辑事件流落盘，方便你随时查看！
#     if dump_contexts_dir:
#         import os, json
#         os.makedirs(dump_contexts_dir, exist_ok=True)
#         with open(os.path.join(dump_contexts_dir, "ecmo_events_debug.json"), "w", encoding="utf-8") as f:
#             json.dump({"raw_events": raw_events, "episodes": episodes}, f, ensure_ascii=False, indent=2)

#     return {
#         "data": data,
#         "evidence_map": evm
#     }


from .extract_ecmo_pipeline import extract_ecmo_pipeline
from .recall import recall_patient
from typing import Dict, Any, Optional
import os, json

def extract_ecmo_field(
    *,
    model: str,
    docs: Dict[str, Any],
    spec: Any, # BundleFieldSpec
    dump_contexts_dir: Optional[str] = None,
) -> Dict[str, Any]:
    
    sub_docs = {dt: docs[dt] for dt in ["big", "course", "disch"] if dt in docs}
    
    contexts = recall_patient(
        sub_docs,
        aliases=spec.aliases,
        k_course=2,
        k_free=1,
    )
    
    final_result = extract_ecmo_pipeline(model=model, docs=docs, contexts=contexts)
    
    # 把秘密通道的数据取出来
    debug_probe = final_result.pop("_debug_probe", {})

    if dump_contexts_dir:
        os.makedirs(dump_contexts_dir, exist_ok=True)
        # 拼装一个极其详尽的报告
        debug_payload = {
            "FINAL_DECISION": {
                "data": final_result["data"],
                "evidence": final_result["evidence_map"]
            },
            "DEBUG_PROBE": debug_probe
        }
        with open(os.path.join(dump_contexts_dir, "ecmo_final_result_debug.json"), "w", encoding="utf-8") as f:
            json.dump(debug_payload, f, ensure_ascii=False, indent=2)

    return final_result




def _sum_lab_values(lab_res: Dict[str, Any]) -> Optional[str]:
    total = 0.0
    unit = ""
    items = lab_res.get("items", [])
    if not items:
        return None
        
    for item in items:
        val = item.get("value")
        u = item.get("unit") or ""
        # 抓取第一个出现的单位
        if not unit and u:
            unit = u.strip()
            
        if isinstance(val, (int, float)):
            total += float(val)
        elif isinstance(val, str):
            import re
            m = re.search(r"(\d+(\.\d+)?)", val)
            if m:
                total += float(m.group(1))
        
    return f"{total}{unit}" if unit else str(total)


# ====================================================================
# 【最终的主调度函数】
# ====================================================================
def extract_all_default_fields(
    *,
    model: str,
    docs: Dict[str, Any],
    patient_dir: str,  # 【注意这里需要接收 pipeline 传来的病人目录】
    ecmo_model: Optional[str] = None,  # 【新增参数】
    lab_specs: Optional[List[LabFieldSpec]] = None,
    panel_specs: Optional[List[PanelFieldSpec]] = None,
    dump_contexts_dir: Optional[str] = None,
) -> Dict[str, Any]:

    out: Dict[str, Any] = {}
    
    # 1. 提取基础 22 字段与出入院信息 (如果这个函数没报错就正常执行)
    from .extract_base import extract_patient_base_bundle
    out["基础信息与出入院"] = extract_patient_base_bundle(
        model=model,
        docs=docs,
        patient_dir=patient_dir
    )

    # 2. 提取常规 Lab 检验 (PCT/CRP/痰培养/输血量等)
    lab_specs = lab_specs or LAB_FIELD_SPECS
    for spec in lab_specs:
        out[spec.key] = extract_lab_field(
            model=model,
            docs=docs,
            spec=spec,
            dump_contexts_dir=dump_contexts_dir,
        )

    # 3. 提取 Panel 面板检查 (急诊生化/血常规/血气等)
    panel_specs = panel_specs or PANEL_FIELD_SPECS
    for spec in panel_specs:
        out[spec.key] = extract_panel_field(
            model=model,
            docs=docs,
            spec=spec,
            dump_contexts_dir=dump_contexts_dir,
        )
    
    # 4. 提取 Flags (既往史/用药史等)
    out[FLAGS_DEFAULT_SPEC.key] = extract_flags_field(
        model=model,
        docs=docs,
        spec=FLAGS_DEFAULT_SPEC,
        dump_contexts_dir=dump_contexts_dir,
    )
    from .field_config import ECMO_BUNDLE_SPEC # 确保导入了配置
    target_ecmo_model = ecmo_model if ecmo_model else model
    out[ECMO_BUNDLE_SPEC.key] = extract_ecmo_field(
        model=target_ecmo_model,
        docs=docs,
        spec=ECMO_BUNDLE_SPEC,
        dump_contexts_dir=dump_contexts_dir,
    )

    # ================= 6. 输血总量 Python 后处理计算 =================
    out["输血情况红细胞总量"] = _sum_lab_values(out.get("红细胞输血提取", {}))
    out["输血情况血小板总量"] = _sum_lab_values(out.get("血小板输血提取", {}))
    out["输血情况血浆总量"]   = _sum_lab_values(out.get("血浆输血提取", {}))

    # ================= 7. 输血总量与是否输血的交叉验证 =================
    if "FLAGS" in out and isinstance(out["FLAGS"].get("data"), dict):
        flags_data = out["FLAGS"]["data"]
        flags_evm = out["FLAGS"]["evidence_map"]

        def _sync_transfusion(flag_key: str, total_val: Optional[str], label: str):
            # 1. 如果有具体的量（且不为 0），强制认定为“是”
            if total_val and str(total_val) not in ("0", "0.0", "None"):
                flags_data[flag_key] = "是"
                flags_evm[flag_key] = f"【系统交叉验证】：已提取到明确的{label}量（{total_val}）"
            else:
                # 2. 如果没有具体的量，看大模型原来的判断
                if flags_data.get(flag_key) is None:
                    # 如果大模型也没抓到，兜底定性为“否”
                    flags_data[flag_key] = "否"
                    flags_evm[flag_key] = f"【系统交叉验证】：未提取到具体的{label}量，且文本未明确提示"

        # 执行交叉验证覆写
        _sync_transfusion("是否红细胞输血", out.get("输血情况红细胞总量"), "红细胞")
        _sync_transfusion("是否血小板输血", out.get("输血情况血小板总量"), "血小板")
        _sync_transfusion("是否血浆输血", out.get("输血情况血浆总量"), "血浆")
    # ====================================================================

    return out





