import json
import re
from typing import List, Dict, Any
from .llm_ollama import ollama_generate

PROMPT = """你是专业的重症医学数据标注员。
任务：从提供的【医疗文本片段】中，识别并抽取 ECMO 相关的“时间线事件”。

只允许输出以下四类事件（event_type）：
1. "ECMO_START"：明确描述正在建立、置入、穿刺、启动 ECMO 的动作，或诊疗经过中明确记录的上机事实（如“于10月30日行ECMO置入”）。
2. "ECMO_STOP"：
   - 明确描述正在撤机、拔除导管、停机的物理动作（如“调整转速为0”、“予拔除导管”）；
   - 诊疗经过/出院小结中明确记录的撤机事实（如“于11.1予ECMO撤机”）；
   以上两种情况均属于已发生的事实，必须标记为ECMO_STOP。
3. "ECMO_PLAN"：带有“拟”、“计划”、“准备”、“考虑”等字眼的未发生动作（如“拟明日撤机”、“考虑上机”）。
4. "ECMO_RUNNING"：仅仅描述 ECMO 正在运行、参数调整或日常护理（如“ECMO流量3.0”、“V-A ECMO支持中”）。

规则：
1.【防时态混淆】：
   - 严禁提取“将来时/计划”：含“拟”、“计划”、“准备”的动作标记为ECMO_PLAN；
   - 允许提取“过去时事实”：诊疗经过中“于X月X日撤机”属于已发生事实，标记为ECMO_STOP；
   - 严禁提取“事后状态”：“撤机后”、“已停用”、“穿刺点换药”等仅描述状态的内容，不标记为ECMO_STOP。
2.【时间提取规则】：
   - 优先提取完整日期时间（如“11月20日 18:30”、“2021-10-30 02:40”）；
   - 若只有月日（如“11.1”、“10-30”），直接提取，不要补充年份/时分；
   - 无明确时间填 null。
3.【证据完整性】：如果时间出现在句首，证据必须包含该时间戳。
4.【防实体混淆】：仅处理ECMO相关事件，严禁将IABP、CRRT的操作标记为ECMO事件。
5.【evidence提取】：必须包含事件的完整上下文（≤180字），确保包含时间和核心动作。
6. 【mode提取】：提到V-A/VV/VA-VV则提取，否则填null。

输出格式要求：
1. 必须以严格的JSON数组格式输出，无任何解释性文字；
2. 未提及ECMO返回空数组[]；
输出格式示例：
[
  {
    "event_type": "ECMO_START",
    "event_time": "14:30",
    "mode": "V-A",
    "evidence": "于14:30顺利置入VA-ECMO导管"
  }
]

【医疗文本片段】
{context}
"""

def extract_ecmo_events(model: str, contexts: List[Dict[str, Any]], max_ctx: int = 50) -> List[Dict[str, Any]]:
    all_events = []
    
    for ctx in contexts[:max_ctx]:
        text = ctx.get("text", "")
        if not text:
            continue
            
        prompt = PROMPT.replace("{context}", text)
        raw_resp = ollama_generate(model, prompt, num_predict=2000)
        
        try:
            # 尝试寻找被 markdown 包裹的 json
            match = re.search(r'\[.*\]', raw_resp, re.DOTALL)
            json_str = match.group(0) if match else raw_resp
            events = json.loads(json_str)
            if not isinstance(events, list):
                events = []
        except Exception:
            events = []
            
        # 补全锚点时间与来源，为后续 Python 排序做准备
        anchor = ctx.get("primary_anchor")
        date_part = str(anchor)[:10] if anchor else "2099-01-01" # 兜底
        doc_type = ctx.get("doc_type", "unknown")
        
        for ev in events:
            # 如果大模型没抓到时间，或者时间不含年份，用当前文本块的锚点时间补全
            raw_time = ev.get("event_time")
            if raw_time and raw_time.strip() != "null":
                if not re.search(r"20\d{2}|年|-|/", raw_time):
                    ev["normalized_time"] = f"{date_part} {raw_time}"
                else:
                    ev["normalized_time"] = raw_time
            else:
                ev["normalized_time"] = str(anchor) if anchor else None
                
            ev["doc_type"] = doc_type
            all_events.append(ev)
            
    return all_events