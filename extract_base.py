from __future__ import annotations
import os
from typing import Dict, Any, List, Optional
from .llm_ollama import ollama_generate, loads_json
from .prompts import admission_prompt, discharge_prompt, first_course_prompt

def _blocks_to_text(blocks: List[Any]) -> str:
    return "\n".join([b.text for b in blocks if b.text.strip()])

def extract_patient_base_bundle(
    model: str,
    docs: Dict[str, Any],
    patient_dir: str,
) -> Dict[str, Any]:
    
    # 初始化 22 个目标字段
    target_keys = [
        "序号", "患者 ID", "就诊唯一号", "性别", "年龄", "身高", "体重",
        "实际结果（生 / 死）", "入院途径", "入院时间", "出院时间", "出院记录时间",
        "出院记录内容", "首次病程记录时间", "首次病程记录内容", "入院记录时间",
        "死亡记录时间", "死亡记录内容", "入院时体温", "入院时收缩压", "入院时舒张压", "入院时心率"
    ]
    data = {k: None for k in target_keys}
    evm = {k: None for k in target_keys}
    meta = {"parse_errors": 0}

    # ==========================================
    # 1. 提取大病历 (Admission Info) - 取前 60 段
    # ==========================================
    big_blocks = docs.get("big", [])
    if big_blocks:
        ctx_text = _blocks_to_text(big_blocks)
        prompt = admission_prompt(ctx_text)
        js = loads_json(ollama_generate(model, prompt, num_predict=4000))
        if not js.get("_parse_error") and isinstance(js.get("data"), dict):
            for k, v in js["data"].items():
                if k in data and v is not None:
                    data[k] = v
                    evm[k] = (js.get("evidence_map") or {}).get(k)
        else:
            meta["parse_errors"] += 1

    # ==========================================
    # 2. 提取出院/死亡信息 - 优先出院记录，兜底病程录末尾
    # ==========================================
    disch_blocks = docs.get("disch", [])
    course_blocks = docs.get("course", [])
    
    # 死亡患者有时没有出院记录，而是直接写在病程录最后
    disch_text = _blocks_to_text(disch_blocks)
    if not disch_text and course_blocks:
        disch_text = _blocks_to_text(course_blocks[-20:])
        
    if disch_text:
        # 控制长度防爆显存
        prompt = discharge_prompt(disch_text[:3000])
        js = loads_json(ollama_generate(model, prompt, num_predict=4000))
        if not js.get("_parse_error") and isinstance(js.get("data"), dict):
            for k, v in js["data"].items():
                if k in data and v is not None:
                    data[k] = v
                    evm[k] = (js.get("evidence_map") or {}).get(k)
        else:
            meta["parse_errors"] += 1

    # ==========================================
    # 3. 提取首次病程记录 - 取病程录前 15 段
    # ==========================================
    if course_blocks:
        ctx_text = _blocks_to_text(course_blocks[:15])
        prompt = first_course_prompt(ctx_text)
        js = loads_json(ollama_generate(model, prompt, num_predict=2000))
        if not js.get("_parse_error") and isinstance(js.get("data"), dict):
            for k, v in js["data"].items():
                if k in data and v is not None:
                    data[k] = v
                    evm[k] = (js.get("evidence_map") or {}).get(k)
        else:
            meta["parse_errors"] += 1

    # ==========================================
    # 4. Python 规则兜底：序号
    # ==========================================
    # 直接用文件夹名称作为追溯序号，方便核对
    patient_folder_name = os.path.basename(patient_dir)
    data["序号"] = patient_folder_name
    evm["序号"] = "系统自动从文件夹提取"
    
    return {
        "data": data,
        "evidence_map": evm,
        "meta": meta
    }