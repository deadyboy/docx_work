import re
from typing import List, Dict, Any

def _sortable_time(t_str: str) -> str:
    """将各种乱七八糟的时间字符串转化为可排序的格式"""
    if not t_str:
        return "2099-12-31 23:59:59" # 空时间沉底
    clean_t = re.sub(r"[年月/.]", "-", str(t_str)).replace("日", " ").strip()
    # 如果只有日期没有时间，给一个默认晚时间保证排在同一天的具体时间之后
    if len(clean_t) == 10:
        clean_t += " 23:59:59"
    return clean_t

def build_ecmo_episodes(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # 1. 过滤掉计划态和纯运行态（我们只关心改变状态的节点）
    valid_events = [e for e in events if e.get("event_type") in ["ECMO_START", "ECMO_STOP"]]
    
    # 2. 按时间严格排序
    valid_events.sort(key=lambda x: _sortable_time(x.get("normalized_time")))
    
    episodes = []
    current_start = None
    modes = []
    
    # 3. 状态机推演
    for e in valid_events:
        etype = e.get("event_type")
        etime = e.get("normalized_time")
        emode = e.get("mode")
        
        if emode and emode.strip() != "null":
            modes.append(emode)
            
        if etype == "ECMO_START":
            # 如果之前没有 start，记录下来；如果有，说明是换管/重新置入，以最早的为准
            if not current_start:
                current_start = e
        
        elif etype == "ECMO_STOP":
            # 只有在有 start 的前提下，stop 才有效（防止孤立的错误 stop）
            if current_start:
                episodes.append({
                    "start_time": current_start.get("normalized_time"),
                    "start_ev": current_start.get("evidence"),
                    "stop_time": etime,
                    "stop_ev": e.get("evidence"),
                    "doc_type": e.get("doc_type")
                })
                # 闭环后清空当前状态，准备迎接可能的下一次 ECMO
                current_start = None
                
    # 处理一直到出院都没下机的特殊情况（带机出院/转院）
    if current_start and not episodes:
        episodes.append({
            "start_time": current_start.get("normalized_time"),
            "start_ev": current_start.get("evidence"),
            "stop_time": None,
            "stop_ev": None,
            "doc_type": current_start.get("doc_type")
        })

    # 提炼 Mode
    final_mode = None
    if modes:
        combined_text = " ".join(modes).upper()
        if "V-A" in combined_text or "VA " in combined_text or "VA-" in combined_text:
            final_mode = "V-A"
        elif "V-V" in combined_text or "VV " in combined_text or "VV-" in combined_text:
            final_mode = "V-V"
        else:
            final_mode = sorted(modes, key=len)[0]

    return episodes, final_mode

def build_ecmo_fields(episodes: List[Dict[str, Any]], final_mode: str) -> Dict[str, Any]:
    
    result = {
        "data": {
            "ECMO方式": final_mode,
            "ECMO上机时间": None,
            "ECMO下机记录时间": None,
            "ECMO下机记录内容": None,
            "是否ECMO脱机成功": None
        },
        "evidence_map": {
            "ECMO方式": "【基于事件流模式推断】" if final_mode else None,
            "ECMO上机时间": None,
            "ECMO下机记录时间": None,
            "ECMO下机记录内容": None,
            "是否ECMO脱机成功": None
        }
    }

    if episodes:
        # 取最后一次闭环作为最终结果（大多数情况下只有一次）
        last_ep = episodes[-1]
        
        result["data"]["ECMO上机时间"] = last_ep["start_time"]
        result["evidence_map"]["ECMO上机时间"] = f"【事件流推演】{last_ep['start_ev']}"
        
        if last_ep["stop_time"]:
            result["data"]["ECMO下机记录时间"] = last_ep["stop_time"]
            result["data"]["ECMO下机记录内容"] = last_ep["stop_ev"]
            result["evidence_map"]["ECMO下机记录时间"] = f"【事件流推演】{last_ep['stop_ev']}"
            result["evidence_map"]["ECMO下机记录内容"] = f"【事件流推演】{last_ep['stop_ev']}"
            
            # 判断脱机成功与否：简单兜底逻辑，具体可根据 evidence 里的“死亡”等词再做判断
            if "死亡" in str(last_ep["stop_ev"]):
                result["data"]["是否ECMO脱机成功"] = "否"
            else:
                result["data"]["是否ECMO脱机成功"] = "是"

    return result