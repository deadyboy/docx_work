"""Field configuration registry.

This module is intentionally simple: it defines per-field extraction specs.
You can extend it to cover all 317 fields by adding new specs and routing rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple


@dataclass(frozen=True)
class LabFieldSpec:
    """Specification for a lab-style extraction."""

    key: str  # output key, e.g. "PCT"
    lab_name: str
    aliases: List[str]
    unit_candidates: List[str]
    # context window sizes
    k_course: int = 2
    k_free: int = 1
    extractor: str = "lab" 

# Minimal starter set. Extend as needed.
LAB_FIELD_SPECS: List[LabFieldSpec] = [
    LabFieldSpec(
        key="PCT",
        lab_name="PCT/降钙素原",
        aliases=["PCT", "降钙素原"],
        unit_candidates=["ng/ml", "ng/mL"],
        k_course=2,
        k_free=1,
        extractor="lab",
    ),
    LabFieldSpec(
        key="CRP",
        lab_name="CRP/C反应蛋白",
        aliases=["CRP", "C反应蛋白", "超敏C反应蛋白"],
        unit_candidates=["mg/L", "mg/l"],
        k_course=2,
        k_free=1,
        extractor="lab",
    ),
    LabFieldSpec(
        key="APACHEII",
        lab_name="APACHEII评分",
        aliases=["APACHE", "APACHE Ⅱ", "APACHE-Ⅱ", "APACHE2", "APACHE 2","APACH", "评分"],
        unit_candidates=[],
        k_course=2,
        k_free=1,
        extractor="score",
    ),
    # === 痰液培养与药敏（纯文本结果，不校验单位） ===
    LabFieldSpec(
        key="痰液真菌培养",
        lab_name="痰液真菌培养",
        aliases=["痰培养", "痰真菌培养", "真菌涂片", "真菌培养", "痰液真菌"],
        unit_candidates=[],  # 为空表示允许纯文本结果（如“阴性”、“白色念珠菌”）
        k_course=2,
        k_free=1,
        extractor="lab",
    ),
    LabFieldSpec(
        key="痰液药敏",
        lab_name="痰液药敏检查",
        aliases=["痰药敏", "药敏", "痰液药敏", "药敏试验"],
        unit_candidates=[],  # 为空表示允许纯文本结果（如“氟康唑敏感”）
        k_course=2,
        k_free=1,
        extractor="lab",
    ),
        LabFieldSpec(
        key="血培养",
        lab_name="血培养",
        aliases=["血培养", "血液培养"],
        unit_candidates=[],  # 为空表示允许纯文本结果（如“阴性”、“白色念珠菌”）
        k_course=2,
        k_free=1,
        extractor="lab",
    ),
    # === 输血情况提取（提取数值，后续供 Python 累加） ===
    LabFieldSpec(
        key="红细胞输血提取",
        lab_name="红细胞输血",
        aliases=["红细胞悬液", "悬浮红细胞", "洗涤红细胞", "少白红细胞", "红细胞"],
        unit_candidates=["u", "单位", "ml", "U"],
        k_course=2,
        k_free=2,
        extractor="lab",
    ),
    LabFieldSpec(
        key="血小板输血提取",
        lab_name="血小板输血",
        aliases=["血小板", "机采血小板", "单采血小板", "治疗量"],
        unit_candidates=["u", "单位", "治疗量", "袋", "ml", "U"],
        k_course=2,
        k_free=2,
        extractor="lab",
    ),
    LabFieldSpec(
        key="血浆输血提取",
        lab_name="血浆输血",
        aliases=["血浆", "冰冻血浆", "新鲜冰冻血浆", "冷沉淀"],
        unit_candidates=["ml", "u", "单位", "U"],
        k_course=2,
        k_free=2,
        extractor="lab",
    ),
]


# ========= Panel spec =========

@dataclass
class AnalyteSpec:
    key: str                    # 结果里的键名（固定）
    aliases: List[str]          # 在文本里可能出现的称呼
    unit_candidates: List[str]  # 可能单位（用于QC）

@dataclass
class PanelFieldSpec:
    key: str                    # 面板字段名，例如 "BIOCHEM_ER", "DIC_PANEL"
    panel_name: str             # 用于提示词显示
    triggers: List[str]         # 面板触发词：必须命中（强过滤）
    analytes: List[AnalyteSpec] # 面板内指标列表
    min_present: int = 2        # 至少几个指标有值才算一次面板事件
    k_course: int = 2
    k_free: int = 1
    extractor: str = "panel"    # 固定 "panel"


# ========= Your panel configs =========

PANEL_FIELD_SPECS: List[PanelFieldSpec] = [
    # --- 急诊生化面板 ---
    PanelFieldSpec(
        key="急诊生化",
        panel_name="急诊生化（肌酐、尿素氮、胆红素、白蛋白）",
        triggers=[
            "生化"
        ],
        analytes=[
            AnalyteSpec(
                key="肌酐",
                aliases=["肌酐", "Cr", "creatinine"],
                unit_candidates=["μmol/L", "umol/L", "mmol/L", "mg/dL", "mg/dl"],
            ),
            AnalyteSpec(
                key="尿素氮",
                aliases=["尿素氮", "尿素", "BUN", "urea"],
                unit_candidates=["mmol/L", "mmol/l", "mg/dL", "mg/dl"],
            ),
            AnalyteSpec(
                key="总胆红素",
                aliases=["总胆红素", "TBil", "总胆"],
                unit_candidates=["μmol/L", "umol/L", "mg/dL", "mg/dl"],
            ),
            AnalyteSpec(
                key="直接胆红素",
                aliases=["直接胆红素", "DBil", "直胆"],
                unit_candidates=["μmol/L", "umol/L", "mg/dL", "mg/dl"],
            ),
            AnalyteSpec(
                key="白蛋白",
                aliases=["白蛋白", "Alb", "albumin"],
                unit_candidates=["g/L", "g/l", "mg/dL", "mg/dl"],
            ),
        ],
        min_present=2,
        k_course=2,
        k_free=1,
    ),

    # --- DIC/凝血面板 ---
    PanelFieldSpec(
        key="凝血功能DIC全套",
        panel_name="DIC全套（TT、APTT、PT、D-二聚体、纤维蛋白原）",
        triggers=[
            "DIC", "凝血酶", "凝血酶原",
            "FDP", "D-二聚体", "D 二聚体", "D二聚体",
            "凝血功能常规+D-二聚体"
        ],
        analytes=[
            AnalyteSpec(
                key="凝血酶时间",
                aliases=["凝血酶时间", "TT"],
                unit_candidates=["秒", "s", "sec"],
            ),
            AnalyteSpec(
                key="活化部分凝血活酶时间",
                aliases=["活化部分凝血活酶时间", "APTT", "aPTT"],
                unit_candidates=["秒", "s", "sec"],
            ),
            AnalyteSpec(
                key="凝血酶原时间",
                aliases=["凝血酶原时间", "PT"],
                unit_candidates=["秒", "s", "sec"],
            ),
            AnalyteSpec(
                key="D-二聚体",
                aliases=["D-二聚体", "D二聚体", "D 二聚体", "D-dimer", "Dimer"],
                unit_candidates=["mg/L", "mg/l", "μg/mL", "ug/mL", "ug/ml"],
            ),
            AnalyteSpec(
                key="纤维蛋白原",
                aliases=["纤维蛋白原", "FIB", "Fib"],
                unit_candidates=["g/L", "g/l", "mg/dL", "mg/dl"],
            ),
        ],
        min_present=2,
        k_course=2,
        k_free=1,
    ),
    # field_config.py 里 PANEL_FIELD_SPECS 追加

    PanelFieldSpec(
        key="血常规",
        panel_name="血常规（PLT/MPV/Hb/WBC/RBC/中性粒绝对值）",
        triggers=["血常规", "血液常规", "血常规+CRP", "CBC", "血象"],
        analytes=[
            AnalyteSpec(
                key="血小板计数", 
                aliases=["血小板", "PLT"], 
                unit_candidates=["10^9/L", "×10^9/L", "10*9/L", "10⁹/L"]
            ),
            AnalyteSpec(
                key="血小板体积",
                aliases=["平均血小板体积", "MPV"], 
                unit_candidates=["fL", "fl"]
            ),
            AnalyteSpec(                        
                key="血红蛋白",
                aliases=["血红蛋白", "Hb", "HGB"],
                unit_candidates=["g/L", "g/l", "g/dL", "g/dl"]
            ),
            AnalyteSpec(
                key="白细胞计数",
                aliases=["白细胞", "WBC"], 
                unit_candidates=["10^9/L", "×10^9/L", "10⁹/L"]
            ),
            AnalyteSpec(
                key="红细胞计数", 
                aliases=["红细胞", "RBC"], 
                unit_candidates=["10^12/L", "×10^12/L", "10¹²/L"]
            ),
            AnalyteSpec(
                key="中性粒细胞绝对值",
                aliases=["中性粒细胞绝对值", "中性粒绝对值", "NEUT#", "NEU#"],
                unit_candidates=["10^9/L", "×10^9/L", "10⁹/L"]
            ),
        ],
        min_present=3,   # 建议比2更严格，避免“只出现1-2个数字就被当成一次血常规”
        k_course=2,
        k_free=1,
    ),

    PanelFieldSpec(
        key="血气分析",
        panel_name="血气分析（乳酸/pH/HCO3-/PaO2/PaCO2）",
        triggers=["血气", "血气分析", "动脉血气", "ABG"],
        analytes=[
            AnalyteSpec(
                        key="乳酸", aliases=["乳酸", "Lac", "Lactate"], unit_candidates=["mmol/L", "mmol/l"]),
            AnalyteSpec(key="pH值", aliases=["pH", "PH"], unit_candidates=[]),
            AnalyteSpec(key="碳酸氢根", aliases=["碳酸氢根", "HCO3", "HCO3-"], unit_candidates=["mmol/L", "mmol/l"]),
            AnalyteSpec(key="氧分压", aliases=["氧分压", "PaO2", "PO2"], unit_candidates=["mmHg", "kPa"]),
            AnalyteSpec(key="二氧化碳分压", aliases=["二氧化碳分压", "PaCO2", "PCO2"], unit_candidates=["mmHg", "kPa"]),
        ],
        min_present=3,
        k_course=2,
        k_free=1,
    ),
]





@dataclass(frozen=True)
class FlagsDomainSpec:
    name: str
    doc_types: List[str]                  # 只在这些文档里召回
    aliases: List[str]                    # 该域召回触发词
    fields: List[Tuple[str, str]]         # 该域负责的字段子集
    include_patterns: Optional[List[str]] = None  # context 必须包含任一（正则）
    exclude_patterns: Optional[List[str]] = None  # context 命中任一则剔除（正则）
    k_course: int = 2
    k_free: int = 1
    max_ctx: int = 12
    stop_ratio: float = 1.0


@dataclass
class FlagsFieldSpec:
    key: str
    aliases: List[str]
    fields: List[Tuple[str, str]]

    k_course: int = 2
    k_free: int = 1
    max_ctx: int = 12
    stop_ratio: float = 1.0

    domains: Optional[List[FlagsDomainSpec]] = None 


FLAGS_DEFAULT_SPEC = FlagsFieldSpec(
    key="FLAGS",
    aliases=[],   # 分域模式下不再用总 aliases；保留为空即可
    fields=[],    # 分域模式下不再用总 fields；保留为空即可
    domains=[
        # 1) 病史域：只允许从既往/否认/病史语境抽
        FlagsDomainSpec(
            name="history",
            doc_types=["big", "disch"],   # 关键：不让它看 course 的诊断段
            aliases=["既往史", "病史", "否认", "高血压", "糖尿病", "心脏病", "脑血管病"],
            fields=[
                ("是否有高血压史", "yesno"),
                ("是否有糖尿病史", "yesno"),
                ("是否有心脏病史", "yesno"),
                ("是否有脑血管病史", "yesno"),
            ],
            include_patterns=[
                r"既往史", r"病史", r"否认", r"个人史", r"家族史"
            ],
            # exclude_patterns=[
            #     r"出院诊断"
            # ],
            k_course=1,
            k_free=2,
            max_ctx=10,
            stop_ratio=1.0,
        ),

        # 2) 诊断域：只从诊断/考虑/修正诊断语境抽
        FlagsDomainSpec(
            name="diagnosis",
            doc_types=["course", "big", "disch", "op", "surg"],
            aliases=["入院诊断", "修正诊断", "出院诊断", "诊断", "考虑", "提示",
                     "急性呼吸窘迫", "急性呼吸衰竭", "ARDS", "心脏骤停", "心源性休克", "心肌梗死", "心肌炎"],
            fields=[
                ("是否急性呼吸窘迫", "yesno"),
                ("是否急性呼吸衰竭", "yesno"),
                ("是否心脏骤停", "yesno"),
                ("是否心源性休克", "yesno"),
                ("是否心肌炎", "yesno"),
                ("是否心肌梗死", "yesno"),
            ],
            include_patterns=[
                r"入院诊断", r"修正诊断", r"出院诊断", r"诊断", r"考虑"
            ],
            k_course=2,
            k_free=1,
            max_ctx=12,
            stop_ratio=1.0,
        ),

        # 3) 处置域：CRRT/机械通气更像“操作/治疗行为”，证据在 course 为主
        FlagsDomainSpec(
            name="procedure",
            doc_types=["course", "big", "disch", "op", "surg"],
            aliases=["CRRT", "CVVH", "CVVHDF", "血液净化", "机械通气", "呼吸机", "气管插管"],
            fields=[
                ("是否行CRRT", "yesno"),
                ("是否进行机械通气", "yesno"),
            ],
            include_patterns=[
                r"行.*CRRT|CRRT|CVVH|CVVHDF|血液净化|气管插管|呼吸机|机械通气"
            ],
            k_course=2,
            k_free=1,
            max_ctx=12,
            stop_ratio=1.0,
        ),

        # 4) 用药域：血管活性药/激素
        FlagsDomainSpec(
            name="medication",
            doc_types=["course", "big", "disch", "op", "surg"],
            aliases=["去甲肾上腺素", "肾上腺素", "多巴胺", "激素", "甲泼尼龙", "地塞米松"],
            fields=[
                ("是否使用去甲肾上腺素", "yesno"),
                ("是否使用肾上腺素", "yesno"),
                ("是否使用多巴胺", "yesno"),
                ("是否使用使用激素", "yesno"),
            ],
            include_patterns=[r"去甲肾上腺素|肾上腺素|多巴胺|激素|甲泼尼龙|地塞米松"],
            k_course=2,
            k_free=1,
            max_ctx=12,
            stop_ratio=1.0,
        ),

        # 5) 输血域：输血/血浆/红细胞/血小板
        FlagsDomainSpec(
            name="transfusion",
            doc_types=["course", "big", "disch", "op", "surg"],
            aliases=["输血","血浆","红细胞","血小板","血浆输血", "红细胞输血", "血小板输血"],
            fields=[
                ("是否红细胞输血", "yesno"),
                ("是否血小板输血", "yesno"),
                ("是否血浆输血", "yesno"),
            ],
            include_patterns=[r"血浆输血|红细胞输血|血小板输血|红细胞悬液"],
            k_course=2,
            k_free=1,
            max_ctx=12,
            stop_ratio=1.0,
        ),
    ],
)







@dataclass(frozen=True)
class BundleFieldSpec:
    """Spec for one bundle extraction (single-object fields)."""
    key: str                                 # output key, e.g. "ECMO"
    aliases: List[str]                       # recall keywords
    name: Optional[str] = None               # bundle name internally
    doc_types: List[str] = field(default_factory=lambda: ["course", "big", "disch", "op"]) # 允许指定只去哪些文档找
    k_course: int = 0                        # 病程录上下延伸段数
    k_free: int = 0                          # 非病程录上下延伸段数
    max_ctx: int = 50                        # 送入 LLM 的最大上下文数量
    stop_ratio: float = 1.0                  # 召回停止阈值


# ECMO 专组配置实例化
ECMO_BUNDLE_SPEC = BundleFieldSpec(
    name="ecmo_bundle",
    key="ECMO",
    doc_types=["course", "big", "disch", "op"], # 明确允许去这些文档召回
    aliases=[
        "ECMO", "体外膜肺", "V-A", "V-V", "VA ECMO", "VV ECMO", 
        "撤机", "脱机", "拔除ECMO", "撤除ECMO", "停用ECMO", "上机", "建立ECMO"
    ],
    k_course=0, # 极简模式：拒绝蔓延
    k_free=0,
    max_ctx=50, 
    stop_ratio=1.0,
)