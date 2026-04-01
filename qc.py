from __future__ import annotations

import re
from typing import Dict, Any, List, Optional

# 日期格式：YYYY-MM-DD
DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")

# 句末分隔符：分号、句号、换行
SENT_SPLIT = re.compile(r"[；;。\n]")

# 数字：支持 0.5, .5, 100, -5.2 等
NUM_RE = re.compile(r"-?(?:\d+(?:\.\d+)?|\.\d+)")


def norm_text(s: str) -> str:
    """
    常见字符形态归一化，减少单位误杀：
    - 全角斜杠／ -> /
    - 全角括号等可按需补充
    """
    if not s:
        return ""
    return (
        s.replace("／", "/")
         .replace("％", "%")
         .replace("，", ",")
         .replace("：", ":")
    )


def trim_evidence(evidence: str, max_len: int = 200) -> str:
    """
    裁剪证据：避免整段病程记录灌进来，保留前部并尽量截断到句子结束符
    """
    if not evidence:
        return ""
    s = evidence.strip()
    if len(s) > 120:
        tail = s[: max_len]
        m = SENT_SPLIT.search(tail[80:])
        if m:
            cut = 80 + m.start() + 1
            return tail[:cut].strip()
    return s[:max_len]


def parse_date_from_text(s: str) -> Optional[str]:
    m = DATE_RE.search(s or "")
    return m.group(1) if m else None


def _coerce_number(x: Any) -> Any:  # 注意：返回类型从 Optional[float] 改为 Any
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return None
            
        # 1. 临床特殊符号保护：包含这些符号的，一律原样保留为字符串
        if any(char in s for char in ["<", ">", "＜", "＞", "="]):
            return s
            
        # 2. 常规数字提取：尝试剥离无关字符并转 float
        clean = re.sub(r"[^0-9\.\-]", "", s)
        try:
            return float(clean)
        except ValueError:
            return None  # 如果剥离后依然无法转为数字（如纯乱码），抛弃
    return None


def _has_number_with_unit(ev: str, unit_candidates: List[str]) -> bool:
    """
    证据中是否出现“数值 + 单位”的组合（强于“出现任意数字”，避免日期数字误判）。
    例如: '0.39ng/ml' / '0.39 ng/ml' / '22.6mg/L'
    """
    if not ev or not unit_candidates:
        return False

    ev_l = ev.lower()
    for u in unit_candidates:
        u_l = u.lower()
        # 数字后可有空格，再跟单位
        if re.search(rf"{NUM_RE.pattern}\s*{re.escape(u_l)}", ev_l):
            return True
    return False


def qc_item_basic(
    item: Dict[str, Any],
    aliases: List[str],
    unit_candidates: List[str],
    context_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    flags: List[str] = []

    # 统一处理 evidence
    ev = norm_text(trim_evidence(item.get("evidence", "")))
    item["evidence"] = ev

    # 1) 证据为空 -> 必杀
    if not ev:
        flags.append("missing_evidence")

    # 2) 证据里没关键词 -> 必杀（防幻觉）
    if aliases and ev and not any(a.lower() in ev.lower() for a in aliases):
        flags.append("evidence_no_alias")

    # 3) 日期同步
    d = parse_date_from_text(ev)
    if d:
        if item.get("date") and item.get("date") != d:
            flags.append("date_overridden")
        item["date"] = d
        item["date_source"] = "evidence"
    else:
        # evidence 无日期：尝试用 window anchor 回填
        anchor = None
        if isinstance(context_meta, dict):
            anchor = context_meta.get("primary_anchor")
        if anchor:
            # primary_anchor 形如 "2019-11-20 23:30:00"
            item["date"] = str(anchor)[:10]
            item["date_source"] = "anchor"
            flags.append("date_from_anchor")
        else:
            flags.append("evidence_no_date")

    # 4) 数值清洗与校验 -> 必杀
    if not unit_candidates:
        # 【分支 A】：不需要单位的项（如痰液培养结果、APACHE评分）
        # 极其宽容：只要大模型输出了文本，就原样保留为字符串
        val = item.get("value")
        if val is None or str(val).strip() == "":
            flags.append("missing_value")
            item["value"] = None
        else:
            item["value"] = str(val).strip()
    else:
        # 【分支 B】：需要单位的项（常规化验、输血等）
        # 经过 _coerce_number 清洗（保留了数字和带 < > 的字符串）
        val = _coerce_number(item.get("value"))
        if val is None:
            flags.append("missing_value")
        else:
            item["value"] = val

    # 5) 证据必须包含“数值+单位”组合 -> 必杀
    if unit_candidates and ev:
        # 注意：这里我们只对“有单位要求”的字段做此校验
        if not _has_number_with_unit(ev, unit_candidates):
            flags.append("evidence_no_number_unit")

    # 6) 单位校验 -> 必杀
    if unit_candidates and ev:
        has_unit = any(u.lower() in ev.lower() for u in unit_candidates)
        if not has_unit:
            flags.append("evidence_no_unit")

    item["qc_flags"] = flags

    # === 硬性过滤条件 ===
    hard_fails = {
        "missing_evidence",
        "evidence_no_alias",
        "missing_value",
        "evidence_no_number_unit",
        "evidence_no_unit",
    }
    item["qc_pass"] = not any(f in hard_fails for f in flags)

    return item


def filter_daily_items(items: List[Dict[str, Any]], threshold: int = 7) -> List[Dict[str, Any]]:
    """
    业务逻辑：如果总记录数 < threshold，全部保留。
    如果 >= threshold，则每天只保留第一条记录。
    """
    if len(items) < threshold:
        return items

    seen_dates = set()
    filtered_items = []
    
    for it in items:
        d = it.get("date")
        # 如果没有日期，安全起见保留（或者你也可以选择丢弃）
        if not d:
            filtered_items.append(it)
            continue
            
        if d not in seen_dates:
            seen_dates.add(d)
            filtered_items.append(it)
            
    return filtered_items