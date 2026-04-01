import json
import re
from typing import List, Dict, Any, Optional
from .llm_ollama import ollama_generate, loads_json
from .prompts import ecmo_op_prompt, ecmo_stop_event_prompt

def _sortable_time(t_str: str) -> str:
    if not t_str:
        return "1970-01-01 00:00:00"
    clean_t = re.sub(r"[年月/.]", "-", str(t_str)).replace("日", " ").strip()
    if len(clean_t) == 10:
        clean_t += " 23:59:59"
    return clean_t

def extract_ecmo_pipeline(model: str, docs: Dict[str, Any], contexts: List[Dict[str, Any]]) -> Dict[str, Any]:
    result_data = {
        "ECMO方式": None, "ECMO上机时间": None, "ECMO下机记录时间": None, 
        "ECMO下机记录内容": None, "是否ECMO脱机成功": None
    }
    result_evm = {k: None for k in result_data.keys()}
    
    # 【新增】：建立一个全能垃圾桶，收集所有中间过程
    debug_probe = {
        "1_pipeline_A_raw_response": None,
        "2_pipeline_B_scanned_contexts": 0,
        "3_pipeline_B_llm_responses": [],
        "4_extracted_stop_events": [],
        "5_raw_contexts": contexts  # 把召回的文本原封不动带出去
    }
    
    # ==========================================
    # 管线 A：从操作记录提取起点
    # ==========================================
    op_blocks = docs.get("op", [])
    op_text = "\n".join([b.text for b in op_blocks if b.text.strip()])
    
    if op_text and any(k in op_text.upper() for k in ["ECMO", "V-A", "V-V", "体外膜肺"]):
        prompt_op = ecmo_op_prompt(op_text[:1500])
        raw_op = ollama_generate(model, prompt_op, num_predict=1000)
        debug_probe["1_pipeline_A_raw_response"] = raw_op
        
        try:
            op_json = loads_json(raw_op)
            if not op_json.get("_parse_error"):
                result_data["ECMO方式"] = op_json.get("ECMO方式")
                result_data["ECMO上机时间"] = op_json.get("ECMO上机时间")
                
                if result_data["ECMO方式"]: result_evm["ECMO方式"] = "【操作记录 LLM 专项提取】"
                if result_data["ECMO上机时间"]: result_evm["ECMO上机时间"] = "【操作记录 LLM 专项提取】"
        except Exception:
            pass

    # ==========================================
    # 管线 B：病程/大病历/出院记录的下机事件
    # ==========================================
    stop_events = []
    # 【修复1】：增加“死亡”、“抢救无效”、“出院”等重症特有终点词
    trigger_words = ["撤机", "脱机", "拔除", "撤除", "停用", "下机", "死亡", "抢救无效", "自动出院", "放弃"]
    for ctx in contexts[:60]:
        text = ctx.get("text", "")
        if not text or not any(kw in text for kw in trigger_words):
            continue 
            
        debug_probe["2_pipeline_B_scanned_contexts"] += 1
        prompt_stop = ecmo_stop_event_prompt(text)
        raw_stop = ollama_generate(model, prompt_stop, num_predict=1000)
        
        # 记录大模型最原始的字符串，抓现行
        debug_probe["3_pipeline_B_llm_responses"].append({
            "block_ids": ctx.get("block_ids"),
            "raw_text": raw_stop
        })
        
        # 采用你系统原生的高鲁棒性解析器
        js_obj = loads_json(raw_stop)
        if js_obj.get("_parse_error"):
            continue # 如果仍然解析失败，通过 debug 文件你能看到是为什么
            
        events = js_obj.get("items", [])
        if isinstance(events, list):
            anchor = ctx.get("primary_anchor")
            date_part = str(anchor)[:10] if anchor else None
            prefix = f"【{ctx.get('doc_type')}】"
            
            for ev in events:
                # ==================================================
                # 【新增拦截核心】：如果大模型返回的是全是 null 的空包，直接扔掉！
                if not ev.get("stop_time") and not ev.get("evidence"):
                    continue
                evidence_text = str(ev.get("evidence", "")).strip()
                if not evidence_text or evidence_text.lower() == "null" or evidence_text == "None":
                    continue
                # ==================================================
                raw_time = ev.get("stop_time")
                if raw_time and str(raw_time).strip() != "null":
                    if date_part and not re.search(r"20\d{2}|年|-|/", str(raw_time)):
                        ev["normalized_time"] = f"{date_part} {raw_time}"
                    else:
                        ev["normalized_time"] = str(raw_time)
                else:
                    ev["normalized_time"] = str(anchor) if anchor else None
                
                ev["evidence"] = prefix + str(ev.get("evidence", ""))
                stop_events.append(ev)

    debug_probe["4_extracted_stop_events"] = stop_events

    # ==========================================
    # 终点对齐
    # ==========================================
    if stop_events:
        stop_events.sort(key=lambda x: _sortable_time(x.get("normalized_time")))
        final_stop = stop_events[-1]
        
        result_data["ECMO下机记录时间"] = final_stop.get("normalized_time")
        result_data["ECMO下机记录内容"] = final_stop.get("evidence")
        result_data["是否ECMO脱机成功"] = final_stop.get("is_success")
        
        result_evm["ECMO下机记录时间"] = final_stop.get("evidence")
        result_evm["ECMO下机记录内容"] = final_stop.get("evidence")
        
    return {
        "data": result_data,
        "evidence_map": result_evm,
        "_debug_probe": debug_probe  # 秘密通道：把探针数据带出去
    }