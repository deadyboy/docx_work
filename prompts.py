from __future__ import annotations

from typing import List, Tuple, Dict, Any


def lab_prompt(lab_name: str, aliases: List[str], context: str) -> str:
    alias_str = "、".join(aliases)
    return f"""你是医疗文本结构化抽取器。

任务：从【输入文本】中抽取所有“{lab_name}（关键词：{alias_str}）”检验事件，必须全量枚举，不可遗漏。

规则：
1) 只能从输入文本中抽取，禁止编造。
2) 仔细辨别数值和单位是否与所提问关键词一致，避免幻觉。(value可以是＞或者＜某个数值的形式，此时value 必须按原文保留为字符串，不要去掉符号)
3) 每条事件必须提供 evidence：必须是输入文本中的连续原文片段（不超过160字），且必须同时包含：日期(YYYY-MM-DD) + 关键词({alias_str}之一) + 数值 + 单位。
4) 日期优先取与该关键词同一子句中的日期；不要把“病程记录抬头时间”误认为检验时间。
5) 若同一日期出现多次该检验，全部列出（time 可为 null）。
6) 输出必须是严格 JSON，不要输出任何解释性文字。
输出JSON格式：
{{
  "items": [
    {{"date": "YYYY-MM-DD", "time": null, "value": number|string|null, "unit": string|null, "evidence": string, "block_ids": [int]}}
  ],
  "count": integer
}}

【输入文本】
{context}
"""




def score_prompt(score_name: str, aliases: List[str], context: str) -> str:
    alias_str = "、".join(aliases)
    return f"""你是医疗文本结构化抽取器。

任务：从【输入文本】中抽取所有“{score_name}（关键词：{alias_str}）”检验事件，必须全量枚举，不可遗漏。

规则：
1) 只能从输入文本中抽取，禁止编造。
2) 仔细辨别数值和单位是否与所提问关键词一致，避免幻觉。(value可以是＞或者＜某个数值的形式，此时value 必须按原文保留为字符串，不要去掉符号)
3) 每条事件必须提供 evidence：必须是输入文本中的连续原文片段（不超过160字），且必须同时包含：关键词({alias_str}之一) + 分值(数字)。单位可以写“分”，也可为 null。
4) 日期(date) 优先取与该关键词同一子句中的日期(YYYY-MM-DD)；如果 evidence 中没有日期，则使用 WINDOW_ANCHOR 的日期（即 WINDOW_ANCHOR 的 YYYY-MM-DD）。
5) 输出必须是严格 JSON，不要输出任何解释性文字。
输出JSON格式：
{{
  "items": [
    {{"date": "YYYY-MM-DD", "time": "HH:MM", "value": number|string|null, "unit": string|null, "evidence": string, "block_ids": [int]}}
  ],
  "count": integer
}}

【输入文本】
{context}
"""




def panel_prompt(panel_name: str, triggers: List[str], analytes_desc: str, min_present: int, context: str) -> str:
    trig_str = "、".join(triggers)
    return f"""你是医疗文本结构化抽取器。

任务：从【输入文本】中抽取所有“{panel_name}”面板检查事件。必须全量枚举，不可遗漏。

面板触发词（必须命中其一）：{trig_str}

面板包含的指标（仅输出这些指标）：
{analytes_desc}

强约束：
1) 只能从输入文本中抽取，禁止编造。
2) 仅当证据中能够确认这是“面板”时才输出：必须命中至少1个触发词；且同一条事件里至少 {min_present} 个指标有明确数值(value可以是＞或者＜某个数值的形式，此时value 必须按原文保留为字符串，不要去掉符号)(value非null)。
3) date：优先取同一子句中的 YYYY-MM-DD；若证据里没有日期，则使用 WINDOW_ANCHOR 的日期。
4) evidence：必须是输入文本中的连续原文片段（<=180字）。应尽量包含触发词，至少需要出现两个指标。
5) 每条事件输出一个 results 字典：对于未出现的指标，value/unit 置 null。
6) 输出必须是严格 JSON，不要输出任何解释性文字。

输出 JSON 格式：
{{
  "items": [
    {{
      "date": "YYYY-MM-DD",
      "time": null,
      "results": {{
        "<KEY>": {{"value": number|string|null, "unit": string|null}},
        "...": {{"value": number|string|null, "unit": string|null}}
      }},
      "evidence": "原文片段",
      "block_ids": [int]
    }}
  ],
  "count": integer
}}

【输入文本】
{context}
"""




def _render_flags_schema(fields: List[Tuple[str, str]]) -> str:
    lines = []
    for name, tp in fields:
        if tp == "yesno":
            lines.append(f'    "{name}": "是"|"否"|null,')
        else:
            lines.append(f'    "{name}": string|null,')
    if lines:
        lines[-1] = lines[-1].rstrip(",")
    return "\n".join(lines)



def flags_prompt(fields: List[Tuple[str, str]], context: str, domain: str = "general") -> str:
    schema = _render_flags_schema(fields)

    domain_rule = ""
    if domain == "history":
        domain_rule = (
            "【域=病史】只判断既往史/否认史/个人史/家族史等内容。"
            "当前诊断（入院/修正/出院/死亡诊断）不等于既往史，不能据此输出“是”。"
        )
    elif domain == "diagnosis":
        domain_rule = (
            "【域=诊断】只依据明确诊断条目输出“是”（例如“入院诊断/修正诊断/出院诊断/死亡诊断：...”）。"
            "若仅出现“考虑/拟/疑似/可能/倾向”等不确定表述，一律输出 null。"
        )
    elif domain in ("procedure", "medication", "transfusion"):
        domain_rule = (
            f"【域={domain}】只在明确已实施/已给予/已输注/已使用时输出“是”（并且必须出现对应的关键词，例如“红细胞输血”必须出现“红细胞”，否则只是“输血”无法判断“是否红细胞输血”为“是”，“血浆输血”同理）。"
            "若出现“必要时/拟/计划/考虑/备/建议/可予”等仅计划或指征表述，一律不予采纳（不能作为最后的证据）。"
        )

    return f"""你是医疗文本结构化抽取器。

任务：从【输入文本】中抽取以下字段。找不到则填 null，禁止编造。

{domain_rule}

规则：
1) 只能从输入文本中抽取，禁止编造和推断。对于所有问题，只能依据明确记载，不得依据常识或概率推断，原文未提及即为null。
2) “是否类”字段只能输出：是 / 否 / null。
3) 输出“是”的条件：必须出现明确肯定或已实施记载（如“诊断：…”“行CRRT”“给予肾上腺素”）。否则输出 null。
4) 只有两种情况可以输出“否”：
   - 明确否认/排除（如“否认心脏病史”“无糖尿病史”“排除心肌炎”等）
   - 明确“未/无/不行/未行/未予/停用/不用”且语义明确指向该事项
   否则一律输出 null（不是“否”）。
5) 每个非 null 字段必须提供 evidence_map[field]：连续原文片段（优先一句话，<=120字），必须包含能支持取值的触发词，严禁不从原文中获取直接编造证据。
6) 输出必须是严格 JSON，不要输出任何解释性文字。

输出 JSON：
{{
  "data": {{
{schema}
  }},
  "evidence_map": {{
    "<字段名>": "<连续原文片段>"
  }}
}}

【输入文本】
{context}
"""

# def ecmo_bundle_prompt(context: str) -> str:
#     """
#     ECMO 专组精简版：负责提取上/下机相关信息。
#     """
#     return f"""你是医疗文本结构化抽取器。

# 任务：从【输入文本】中抽取 ECMO 的 5 个字段。只能基于输入文本，不得编造。

# 字段（必须输出这些 key）：
# 1) ECMO方式
# 2) ECMO上机时间
# 3) ECMO下机记录时间
# 4) ECMO下机记录内容
# 5) 是否ECMO脱机成功

# 规则：
# 1) “时间”字段允许格式多样。若原文只有时分，请直接提取时分，不要自行推断日期。如果句子的开头有时期（例如年，月，日），请尽量提取完整日期时间（如“11月20日 18:30”）。
# 2) 【极度重要防错 1 - 严禁时态混淆】：严禁把包含“ECMO撤机后”、“已撤机”、“脱机后”等描述既往状态的记录提取为下机时间和内容！你必须在原文中找到正在发生拔管动作的那一天。同理，找上机时间时，也要找正在建立或刚刚上机的那一刻（如“ECMO上机成功后”）。
# 3) 【极度重要防错 2 - 严禁实体混淆】：ECMO不等于IABP，也不等于CRRT！严禁把“拔除IABP导管”、“CRRT下机”当做ECMO的下机。
# 4) 若文本中没有明确提及某字段，填 null。
# 5) evidence_map：每个字段必须摘录严格对应的原文（<=180字），找不到填 null。"ECMO下机记录时间"的 evidence 必须包含能够明确指向下机时间的触发词（如“撤除”、“拔除”、“脱机”等），且必须包含时间信息。
# 6) 输出必须是严格 JSON，不要输出解释性文字。
# 输出 JSON 格式：
# {{
#   "data": {{
#     "ECMO方式": "string|null",
#     "ECMO上机时间": "string|null",
#     "ECMO下机记录时间": "string|null",
#     "ECMO下机记录内容": "string|null",
#     "是否ECMO脱机成功": "是"|"否"|null
#   }},
#   "evidence_map": {{
#     // 与上面字段对应
#   }}
# }}

# 【输入文本】
# {context}
# """
# def ecmo_bundle_prompt(context: str) -> str:
#     """
#     ECMO 专组精简版：负责提取上/下机相关信息。
#     """
#     return f"""你是医疗文本结构化抽取器。

# 任务：从【输入文本】中抽取 ECMO 的 5 个字段。只能基于输入文本，不得编造。

# 字段（必须输出这些 key）：
# 1) ECMO方式
# 2) ECMO上机时间
# 3) ECMO下机记录时间
# 4) ECMO下机记录内容
# 5) 是否ECMO脱机成功

# 规则：
# 1) “时间”字段允许格式多样。如果句子的开头有时期（例如年，月，日），请尽量提取完整日期时间（如“11月20日 18:30”）。
# 2) 【极度重要防错 1 - 严禁时态混淆】：医疗文书中包含大量“过去时”和“计划/意图”。
#    - 严禁提取“将来时/计划”：带有“拟”、“计划”、“准备”、“拟今予停用”等字眼的记录，只是医生的计划，动作并未发生，绝对不能作为下机时间！
#    - 严禁提取“过去时”：带有“撤机后”、“已停用”、“穿刺点换药”、“拔除缝线”等字眼的记录，是事后状态，绝对不能作为下机时间！
#    - 你必须寻找真正执行物理动作的那一刻（如“调整转速为0”、“予拔除导管”、“顺利撤除”）。
# 3) 【极度重要防错 2 - 严禁实体混淆】：ECMO不等于IABP，也不等于CRRT！严禁把“拔除IABP导管”、“CRRT下机”当做ECMO的下机。
# 4) 若文本中没有明确提及某字段，填 null。
# 5) evidence_map：每个字段必须摘录严格对应的原文（<=180字），找不到填 null。"ECMO下机记录时间"的 evidence 必须包含真正的拔管/停机动作触发词。注意：如果时间出现在一段话或长句的开头（如“于XX月XX日XX时...最终拔除”），请大胆将该句首时间作为下机时间提取！
# 6) 输出必须是严格 JSON，不要输出解释性文字。

# 输出 JSON 格式：
# {{
#   "data": {{
#     "ECMO方式": "string|null",
#     "ECMO上机时间": "string|null",
#     "ECMO下机记录时间": "string|null",
#     "ECMO下机记录内容": "string|null",
#     "是否ECMO脱机成功": "是"|"否"|null
#   }},
#   "evidence_map": {{
#     // 与上面字段对应
#   }}
# }}

# 【输入文本】
# {context}
# """




def admission_prompt(context: str) -> str:
    return f"""你是医疗文本结构化抽取器。

任务：从【大病历/入院记录】的节选中提取患者基本信息与入院体征。找不到填 null，禁止编造。

字段提取规则：
1) 血压拆分：若记录为 "Bp 133/99mmHg"，则收缩压=133，舒张压=99。若原文写“测不出”，则收缩压和舒张压均直接填“测不出”。
2) 心率：优先从“心脏”专科查体（如“心率103次/分”）中提取。
3) 身高、体重：若原文写“未测”、“未查”，一律输出 null。
4) 体温：提取具体数字，如 36.7。
5) 其他诊断：提取原文中提到的所有补充诊断，不允许遗漏和删减！如果没有其他诊断，填 null。
6) 必须提供 evidence_map，摘录对应的短句原文（<=100字）。

输出 JSON 格式：
{{
  "data": {{
    "患者 ID": "string|null",
    "就诊唯一号": "string|null",
    "性别": "string|null",
    "年龄": "string|null",
    "身高": "string|null",
    "体重": "string|null",
    "入院途径": "string|null",
    "入院时间": "string|null",
    "入院时体温": "string|null",
    "入院时收缩压": "string|null",
    "入院时舒张压": "string|null",
    "入院时心率": "string|null",
    "其他诊断": "string|null"
  }},
  "evidence_map": {{
    // 与上面字段对应，填入原文片段
  }}
}}

【输入文本】
{context}
"""

def discharge_prompt(context: str) -> str:
    return f"""你是医疗文本结构化抽取器。

任务：从【出院/死亡记录】的节选中提取结局信息。找不到填 null，禁止编造。

字段提取规则：
1) 实际结果（生/死）：若文本明确出现“宣布临床死亡”、“抢救无效死亡”等，填“死”；若是常规出院、转院、自动出院等，均填“生”。
2) 记录内容：提取核心的出院小结或死亡原因/抢救经过，保留核心逻辑（<=150字）。
3) 必须提供 evidence_map 摘录原文。

输出 JSON 格式：
{{
  "data": {{
    "实际结果（生 / 死）": "生"|"死"|null,
    "出院时间": "string|null",
    "出院记录时间": "string|null",
    "出院记录内容": "string|null",
    "死亡记录时间": "string|null",
    "死亡记录内容": "string|null"
  }},
  "evidence_map": {{
    // 与上面字段对应
  }}
}}

【输入文本】
{context}
"""

def first_course_prompt(context: str) -> str:
    return f"""你是医疗文本结构化抽取器。

任务：从【病程录】的头部节选中提取首次病程记录。找不到填 null。

字段提取规则：
1) 首次病程记录内容：优先提取“病例特点”、“拟诊讨论”或第一天的核心病情总结（<=200字）。

输出 JSON 格式：
{{
  "data": {{
    "首次病程记录时间": "string|null",
    "首次病程记录内容": "string|null"
  }},
  "evidence_map": {{
    // 与上面字段对应
  }}
}}

【输入文本】
{context}
"""


def ecmo_op_prompt(context: str) -> str:
    """管线 A：针对操作记录的专项提取"""
    return f"""你是专业的重症医学数据提取器。
任务：从提供的【操作记录】中提取 ECMO 的建立信息。

规则：
1. ECMO方式：明确提取是 V-A、V-V 或其他模式。若文本未提及，填 null。
2. ECMO上机时间：提取明确的操作发生时间。优先提取完整的“YYYY-MM-DD HH:MM”，若只有时间或日期，请尽量根据文本上下文提取。若未记录时间，填 null。
3. 严格输出 JSON，禁止任何额外文本。

输出 JSON 格式：
{{
  "ECMO方式": "string|null",
  "ECMO上机时间": "string|null"
}}

【操作记录】
{context}
"""

def ecmo_stop_event_prompt(context: str) -> str:
    """管线 B：针对病程/大病历/出院记录的下机事件提取"""
    return f"""你是专业的重症医学数据提取器。
任务：从提供的【医疗文本片段】中，寻找明确的 ECMO “撤机/下机”事件。

规则：
1. 【极度重要防错 1 - 严禁时态混淆】：医疗文书中包含大量“过去时”和“计划/意图”。
  - 严禁提取“将来时/计划”：带有“拟”、“计划”、“准备”、“拟今予停用”等字眼的记录，只是医生的计划，动作并未发生，绝对不能作为下机时间！
  - 严禁提取“过去时”：带有“撤机后”、“已停用”、“穿刺点换药”、“拔除缝线”等字眼的记录，是事后状态，绝对不能作为下机时间！
  - 你必须寻找真正执行物理动作的那一刻，或明确记录的撤机事实（如“调整转速为0”、“予拔除导管”、“顺利撤除”）。
2. 【极度重要防错 2 - 严禁实体混淆】：
  - ECMO不等于IABP，也不等于CRRT！严禁把“拔除IABP导管”、“CRRT下机”当做ECMO的下机。
  - 若文本明确记录患者“临床死亡”、“抢救无效”、“自动出院”或“放弃抢救”，这等同于 ECMO 终止。
3. 【带机转院特例】：若明确记录患者在“ECMO持续应用/维持”的状态下“转上级医院”或“出院”，这也是本院记录的终点！必须提取出院/转院时间作为 stop_time。
4. 【判断是否成功】：根据下机事实判断脱机是否成功。若记载“死亡”、“自动出院”、“放弃抢救”、“带机转院”则为“否”；若记载“顺利撤除”、“拔除”且未提示死亡，则为“是”。
5. 若片段中没有下机事实，items 数组必须为空 []。
6. evidence：每个字段必须摘录严格对应的原文（<=180字），找不到填 null。"ECMO下机记录时间"的 evidence 必须包含真正的拔管/停机动作触发词。注意：如果时间出现在一段话或长句的开头（如“于XX月XX日XX时...最终拔除”），请大胆将该句首时间作为下机时间提取！
7. 严格输出 JSON 对象，禁止任何额外文本。
输出 JSON 格式：
{{
  "items": [
    {{
      "stop_time": "string|null",
      "evidence": "string",
      "is_success": "是"|"否"|null
    }}
  ]
}}

【医疗文本片段】
{context}
"""