# 顶层架构蓝图：docx_work × pdf_work 融合 Agent 体系

> 文档版本：2026-04  
> 适用范围：ICU/重症医疗数据结构化抽取系统，面向 2025–2026 生产环境部署

---

## 目录

1. [两套 pipeline 端到端流程对比](#1-两套-pipeline-端到端流程对比)
2. [自动输入类型判别与顶层分发](#2-自动输入类型判别与顶层分发)
3. [LLM 层抽象：Ollama / vLLM 兼容性对齐](#3-llm-层抽象ollamavllm-兼容性对齐)
4. [LangGraph 合流方案](#4-langgraph-合流方案)
5. [生产环境 Agent 底座选型建议](#5-生产环境-agent-底座选型建议)
6. [落地操作路径与代码目录](#6-落地操作路径与代码目录)

---

## 1. 两套 pipeline 端到端流程对比

### 1.1 docx_work — 结构化文本 pipeline

```
患者文件夹（.docx × 5）
        │
        ▼
  [load_patient.py]
  DOCX → Block 序列
  （带 anchor_dt 时间锚）
        │
        ▼
  [recall.py]
  关键词命中 → 滑动窗口 → 合并去重
  输出：List[context_dict]
        │
        ▼
  [router.py] extract_all_default_fields()
  ┌──────────────────────────────────────┐
  │ 按字段类型分发                        │
  │ lab_field  → extract_lab_items()     │
  │ panel_field→ extract_panel_items()   │
  │ flags_field→ extract_flags_items()   │
  │ ecmo_field → extract_ecmo_pipeline() │
  │ base       → extract_base_bundle()   │
  └──────────────────────────────────────┘
        │ each: prompt → Ollama → JSON
        ▼
  [qc.py]
  evidence 校验 / 数值清洗 / 去重排序
        │
        ▼
  Dict[str, Any]  →  JSON 落盘
```

**关键特点：**
- 输入是**纯文本**，召回粒度是 Block（段落）
- LLM 只调用文字模型（qwen3:8b / qwen14b），走 `/api/generate`
- 配置驱动（`field_config.py` dataclass），新增字段不需改代码
- 每个抽取器独立、可并行、可重试

---

### 1.2 pdf_work — 图像/PDF 护理记录 pipeline

```
图片文件夹（.png / .jpg 护理记录单）
        │
        ▼
  [router.py] classify_icu_records()
  PaddleOCR 识别表头
  "单(一)" → data_record1/
  "单(二)" → data_record2/
        │
        ▼
  [cutter_worker.py]
  表格区域检测 → 按列切割
  输出：block_001_L.png / _M.png / _R.png
        │
        ▼
  [main_batch.py] process_three_columns_batch()
  ┌─────────────────────────────────────────┐
  │ 三列并行识别（每列独立 prompt）            │
  │ L 列: PROMPT_L → 生命体征               │
  │ M 列: PROMPT_M → 出入量                 │
  │ R 列: PROMPT_R → 护理记录               │
  └─────────────────────────────────────────┘
        │ each: image + prompt → Ollama vision → JSON
        ▼
  [global_merger.py]
  合并三列 JSON → 按时间点整合
        │
        ▼
  List[Dict]  →  JSON 落盘
```

**关键特点：**
- 输入是**图像**，OCR/视觉模型处理
- LLM 调用**多模态视觉模型**（qwen2.5vl:72b），走 `/api/chat` + images
- **没有召回环节**（每个时间切片直接送全量图片）
- PaddleOCR 做表单分类路由，依赖独立 Python 环境

---

### 1.3 核心差异汇总

| 维度 | docx_work | pdf_work |
|---|---|---|
| **输入类型** | .docx 文本文档 | .png/.jpg 护理记录图像 |
| **解析方式** | python-docx Block 序列 | PaddleOCR + OpenCV 切图 |
| **召回策略** | 关键词 + 滑动窗口 | 无（全图送入） |
| **LLM 模式** | 纯文字推理 | 多模态视觉推理 |
| **LLM 模型** | qwen3:8b / qwen14b | qwen2.5vl:72b |
| **Ollama API** | `/api/generate` | `/api/chat` + images |
| **配置驱动** | ✅ field_config.py | ❌ 硬编码 prompt |
| **QC 层** | ✅ qc.py evidence 校验 | ❌ 无正式 QC |
| **Agent 就绪度** | ⭐⭐⭐⭐ (模块化好) | ⭐⭐ (强耦合) |

---

## 2. 自动输入类型判别与顶层分发

顶层 agent 接收到一个患者目录时，需要自动判别应该走哪条 pipeline。

### 2.1 判别逻辑（已实现于 `agent/input_router.py`）

```python
from docx_work.agent.input_router import detect_input_type, route_input

result = route_input("/data/patient_001")
print(result.input_type)   # "docx" | "image" | "pdf" | "mixed" | "unknown"
print(result.has_canonical_docx_layout)   # True/False
print(result.metadata)     # {"n_docx": 5, "canonical_files_found": [...]}
```

**判别规则：**

| 目录内容 | 判别结果 |
|---|---|
| 只有 .docx（含标准文件名） | `"docx"` |
| 只有 .png/.jpg | `"image"` |
| 只有 .pdf | `"pdf"` |
| 混合（docx + 图片/PDF） | `"mixed"` |
| 无法识别的文件类型 | `"unknown"` |

### 2.2 批处理目录路由（多患者并行）

```python
from docx_work.agent.input_router import classify_batch_directory

all_patients = classify_batch_directory("/data/all_patients")
for pid, route in all_patients.items():
    if route.input_type == "docx":
        run_docx_pipeline(pid, route.docx_files)
    elif route.input_type == "image":
        run_vision_pipeline(pid, route.image_files)
    elif route.input_type == "mixed":
        run_docx_pipeline(pid, route.docx_files)
        run_vision_pipeline(pid, route.image_files)
```

### 2.3 顶层 Agent 分发伪代码

```python
# top_level_agent.py
def dispatch_patient(patient_dir: str, model: str):
    route = route_input(patient_dir)

    if route.input_type == "docx":
        # docx_work pipeline (text LLM)
        return run_patient_agent(patient_dir, model=model, backend="ollama")

    elif route.input_type in ("image", "pdf"):
        # pdf_work pipeline (vision LLM)
        return run_vision_agent(patient_dir, model="qwen2.5vl:72b", backend="ollama")

    elif route.input_type == "mixed":
        # Both pipelines in parallel
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor() as ex:
            docx_fut = ex.submit(run_patient_agent, patient_dir, model)
            vision_fut = ex.submit(run_vision_agent, patient_dir, "qwen2.5vl:72b")
        return merge_results(docx_fut.result(), vision_fut.result())

    else:
        raise ValueError(f"Cannot process {patient_dir}: {route.error}")
```

---

## 3. LLM 层抽象：Ollama/vLLM 兼容性对齐

### 3.1 统一 LLM Client（已实现于 `llm_client.py`）

```
llm_client.py
├── generate(model, prompt, backend=...)
│   ├── backend="ollama" → _ollama_generate()  → /api/generate 或 /api/chat
│   └── backend="vllm"  → _vllm_generate()   → /v1/chat/completions (OpenAI-compat)
└── loads_json(text)  →  Dict (统一 _parse_error 契约)
```

**调用示例：**

```python
# 切换到 vLLM（生产环境）
import os
os.environ["LLM_BACKEND"] = "vllm"
os.environ["VLLM_BASE_URL"] = "http://gpu-server:8000"

from docx_work.llm_client import generate, loads_json

raw = generate(model="Qwen/Qwen2.5-7B-Instruct", prompt=my_prompt)
result = loads_json(raw)
```

```python
# 多模态图像（Ollama vision）
from docx_work.llm_client import generate
raw = generate(
    model="qwen2.5vl:72b",
    prompt="请从图中提取生命体征...",
    backend="ollama",
    image_paths=["./slice_001_L.png"],
)
```

### 3.2 Ollama vs vLLM 协议对齐

| 特性 | Ollama | vLLM |
|---|---|---|
| **文字推理** | `POST /api/generate` + `format: "json"` | `POST /v1/chat/completions` + `response_format: {"type": "json_object"}` |
| **视觉推理** | `POST /api/chat` + `images: [base64]` | `POST /v1/chat/completions` + content 中 image_url |
| **温度控制** | `options.temperature` | `temperature` 顶层参数 |
| **最大 token** | `options.num_predict` | `max_tokens` |
| **JSON 模式** | 原生支持（`format: "json"`） | 支持（`response_format`） |
| **结构化工具调用** | ❌（当前不支持） | ✅（OpenAI function calling） |
| **流式输出** | `stream: true` | `stream: true` (SSE) |

### 3.3 结构化工具调用的未来统一方向

vLLM 支持 OpenAI Function Calling，可以直接把每个 extractor 定义为一个函数 schema：

```python
# 未来：把 lab 抽取结构化为 function call（vLLM only）
EXTRACT_LAB_FUNCTION = {
    "name": "extract_lab_results",
    "description": "从医疗文本中提取某检验指标的所有时序记录",
    "parameters": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string"},
                        "time": {"type": "string"},
                        "value": {"type": "number"},
                        "unit": {"type": "string"},
                    }
                }
            }
        }
    }
}
```

当 Ollama 也支持 function calling 后（部分版本已支持），两者可以完全统一，届时只需在 `llm_client.py` 中加一个 `tools` 参数即可。

---

## 4. LangGraph 合流方案

### 4.1 为什么选 LangGraph？

| 框架 | 优点 | 缺点 |
|---|---|---|
| **LangGraph** | 显式状态图、条件边、可 checkpoint、可流式、活跃维护 | 依赖 LangChain 生态 |
| LangChain AgentExecutor | 熟悉，文档多 | 不可见状态、不够灵活 |
| AutoGen | 多智能体，对话驱动 | 状态管理复杂、不适合批处理 |
| 自定义 while 循环 | 零依赖 | 无 checkpoint、无流式 |

**结论：LangGraph 是 2025–2026 最适合本项目的 Agent 框架。**

本项目的 `agent/graph.py` 已实现完整的 LangGraph 图，同时提供无依赖 fallback。

### 4.2 已实现的 LangGraph 图

```
START
  │
  ▼
[load_docs] ── 解析 DOCX → Block 序列 ── 注入 state["docs"]
  │
  ▼
[plan] ── 构建 pending_fields 列表（可以自定义字段子集）
  │
  ▼
[extract] ── 逐字段调用 TOOL_REGISTRY[field_key](state)
  │
  ├─ ok=True ──────────────────────────────────────┐
  │                                                │
  ├─ ok=False, retries < max ──→ 重新入队到队首    │
  │                                                │
  └─ ok=False, retries >= max ──→ 记录 errors      │
           │                                        │
           └─ pending_fields 还有？────────────────►│
                                                    │
                                           (全部完成或失败)
                                                    │
                                                    ▼
                                             [postprocess]
                                              输血总量计算
                                              FLAGS 交叉验证
                                                    │
                                                    ▼
                                                   END
```

### 4.3 使用示例

```python
from docx_work.agent import run_patient_agent

# 最简调用（无 langgraph 也可运行，自动 fallback）
result = run_patient_agent(
    patient_dir="/data/patients/patient_001",
    model="qwen3:8b",
    ecmo_model="qwen14b-structured:latest",
)

print(result["results"]["PCT"])   # {'items': [...], 'count': N}
print(result["messages"])         # 完整审计日志
print(result["errors"])           # 哪些字段失败了
```

```python
# 高级：只抽取部分字段（用于调试或增量更新）
result = run_patient_agent(
    patient_dir="/data/patients/patient_001",
    model="qwen3:8b",
    custom_fields=["PCT", "CRP", "APACHEII"],
)
```

```python
# 高级：使用 LangGraph 原生接口获取逐步流输出
from docx_work.agent.graph import build_patient_graph
from docx_work.agent.state import make_initial_state

graph = build_patient_graph()
state = make_initial_state(
    patient_dir="/data/patients/patient_001",
    model="qwen3:8b",
)

for event in graph.stream(state):
    node_name = list(event.keys())[0]
    print(f"Node [{node_name}] executed")
```

### 4.4 从 pdf_work 接入 LangGraph

pdf_work 目前没有 LangGraph 集成。接入路径如下：

```python
# agent/vision_tools.py (建议在 pdf_work 中添加)
from pathlib import Path
import json

def tool_vision_classify(image_dir: str) -> dict:
    """PaddleOCR 分类表单类型"""
    # 调用 pdf_work/router.py::classify_icu_records()
    ...

def tool_vision_cut(image_path: str, output_dir: str) -> dict:
    """调用切图子进程（PaddleOCR 独立环境）"""
    ...

def tool_vision_extract(slice_dir: str, model: str) -> dict:
    """多模态 LLM 提取三列数据"""
    # 调用 main_batch.py::process_three_columns_batch()
    ...
```

然后在 LangGraph 中：

```python
vision_graph = StateGraph(VisionState)
vision_graph.add_node("classify", tool_vision_classify)
vision_graph.add_node("cut", tool_vision_cut)
vision_graph.add_node("extract_l", lambda s: tool_vision_extract(s, "L"))
vision_graph.add_node("extract_m", lambda s: tool_vision_extract(s, "M"))
vision_graph.add_node("extract_r", lambda s: tool_vision_extract(s, "R"))
vision_graph.add_node("merge", tool_vision_merge)
```

---

## 5. 生产环境 Agent 底座选型建议

### 5.1 架构适合度评估（面向 2025–2026）

| 维度 | docx_work | pdf_work | 建议 |
|---|---|---|---|
| **代码可维护性** | ⭐⭐⭐⭐⭐ 配置驱动，模块化 | ⭐⭐ 硬编码 prompt | docx_work 更佳 |
| **Agent 就绪度** | ⭐⭐⭐⭐ 有 router、spec、qc | ⭐⭐ 无架构层 | docx_work 更佳 |
| **LangGraph 兼容** | ✅ 已实现 | ⚠️ 需重构 | docx_work 起步 |
| **多模态支持** | ❌ 纯文字 | ✅ 图像/PDF | pdf_work 必要 |
| **召回质量** | ⭐⭐⭐⭐ 关键词+窗口 | ❌ 无召回 | docx_work 更佳 |
| **QC/证据追溯** | ⭐⭐⭐⭐ evidence_map | ❌ 无 QC | docx_work 更佳 |
| **批处理效率** | ✅ 多进程多端口 | ✅ 多进程 | 相当 |

**结论：以 docx_work 架构为底座，把 pdf_work 的视觉能力作为可选工具模块集成进来。**

### 5.2 推荐的统一生产架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Top-Level Orchestrator                    │
│                  (input_router + dispatch)                   │
└──────────────────────┬──────────────────┬───────────────────┘
                       │                  │
              [DOCX Pipeline]    [Vision Pipeline]
                       │                  │
         ┌─────────────▼──┐    ┌──────────▼──────────┐
         │  LangGraph     │    │  LangGraph           │
         │  PatientAgent  │    │  VisionAgent         │
         │  (agent/*)     │    │  (pdf_work/agent/*)  │
         └─────────────┬──┘    └──────────┬───────────┘
                       │                  │
         ┌─────────────▼──────────────────▼───────────┐
         │           Unified LLM Client               │
         │           llm_client.py                    │
         │  Ollama (text/vision) ↔ vLLM (OpenAI-API) │
         └────────────────────────────────────────────┘
```

### 5.3 Ollama vs vLLM 生产选型

| 场景 | 建议 |
|---|---|
| 研究 / 小规模（< 100 患者/天） | Ollama，简单易维护 |
| 生产 / 大规模（> 1000 患者/天） | vLLM，更高吞吐量，PagedAttention |
| 多 GPU 节点 | vLLM tensor parallel |
| 多模态（护理记录图像） | 两者均可，qwen2.5vl:72b |
| 混合（Ollama 测试 + vLLM 生产） | 通过 `LLM_BACKEND` 环境变量无缝切换 |

---

## 6. 落地操作路径与代码目录

### 6.1 最终代码目录结构

```
docx_work/
├── llm_client.py           ← 新增：统一 LLM 客户端（Ollama + vLLM）
├── llm_ollama.py           ← 保留：旧代码 backward-compat，不动
├── field_config.py         ← 现有：配置驱动字段定义
├── router.py               ← 现有：字段路由调度
├── recall.py               ← 现有：召回引擎
├── extract_lab.py          ← 现有：Lab 抽取器
├── extract_panel.py        ← 现有：Panel 抽取器
├── extract_flag.py         ← 现有：Flag 抽取器
├── extract_ecmo_pipeline.py← 现有：ECMO 专项 pipeline
├── extract_base.py         ← 现有：基础信息抽取器
├── qc.py                   ← 现有：QC 校验
├── load_patient.py         ← 现有：DOCX 加载
├── pipeline_patient.py     ← 现有：单患者 pipeline（可被 agent 取代）
├── run_parallel.py         ← 现有：多进程并行
├── ARCHITECTURE.md         ← 新增：本文档
└── agent/                  ← 新增：Agent 包
    ├── __init__.py         ← 新增：公开 API
    ├── state.py            ← 新增：PatientState TypedDict
    ├── tools.py            ← 新增：Tool 注册表（包装现有 extractor）
    ├── graph.py            ← 新增：LangGraph 图 + fallback
    └── input_router.py     ← 新增：输入类型自动判别
```

### 6.2 分阶段落地路线图

#### 阶段 0（已完成）：代码分析与架构设计
- [x] 分析两个仓库的现有架构
- [x] 识别 Agent 化的关键阻碍和机会
- [x] 完成本架构文档

#### 阶段 1（已完成）：Tool 化 + LangGraph 骨架
- [x] `llm_client.py`：统一 LLM 客户端（Ollama + vLLM）
- [x] `agent/state.py`：PatientState 定义
- [x] `agent/tools.py`：TOOL_REGISTRY（包装所有 extractor）
- [x] `agent/graph.py`：LangGraph StateGraph + fallback
- [x] `agent/input_router.py`：输入类型自动判别

#### 阶段 2（建议下一步）：状态增强与自适应召回
- [ ] 安装 langgraph：`pip install langgraph`
- [ ] 在 `graph.py` 中添加 `node_retry_expand`：失败时扩大 k_course/k_free 再重试
- [ ] 跨字段推理：ECMO 状态 → 影响 FLAGS 字段（参见 §6.4）
- [ ] 自适应召回：召回为空时自动增加 aliases

#### 阶段 3（长期目标）：融合视觉 pipeline
- [ ] 在 pdf_work 中添加 `agent/` 包，复用本文档的架构
- [ ] 顶层 orchestrator 实现 classify_batch_directory + dispatch
- [ ] 统一 JSON schema（两个 pipeline 输出格式对齐）

### 6.3 快速开始（5分钟）

```bash
# 1. 安装依赖
pip install langgraph          # Agent 框架（可选，有 fallback）
pip install requests           # HTTP 客户端（已有）
pip install json_repair        # JSON 修复（可选，推荐）

# 2. 确保 Ollama 运行中
ollama serve &
ollama pull qwen3:8b

# 3. 运行一个患者（Agent 模式）
python -c "
from docx_work.agent import run_patient_agent
result = run_patient_agent(
    patient_dir='/data/patients/patient_001',
    model='qwen3:8b',
)
print('Fields extracted:', list(result['results'].keys()))
print('Errors:', result['errors'])
"

# 4. 测试输入路由
python -c "
from docx_work.agent import detect_input_type
print(detect_input_type('/data/patients/patient_001'))
"
```

### 6.4 跨字段推理示例（阶段 2 预告）

```python
# 在 postprocess 节点中添加推断规则
def _cross_field_inference(results: dict) -> dict:
    ecmo = results.get("ECMO", {}).get("data", {})
    flags = results.get("FLAGS", {}).get("data", {})

    # 规则 1：如果 ECMO 存在且脱机成功=否/无，不应该有"ECMO脱机成功=是"
    if ecmo.get("是否ECMO脱机成功") == "否":
        # 这个推断已在 ecmo_pipeline.py 中做，这里做二次校验
        pass

    # 规则 2：如果提取到 CRRT 操作记录，强制标记为"是"
    crrt_flag = flags.get("是否行CRRT")
    ecmo_contexts = results.get("_ecmo_contexts", [])
    if any("CRRT" in ctx.get("text", "") for ctx in ecmo_contexts):
        if crrt_flag != "是":
            flags["是否行CRRT"] = "是"
            results["FLAGS"]["evidence_map"]["是否行CRRT"] = "【跨字段推理】：ECMO上下文中发现CRRT记录"

    return results
```

### 6.5 环境变量参考

```bash
# LLM Backend 切换（Ollama ↔ vLLM）
export LLM_BACKEND=ollama          # 或 vllm
export OLLAMA_HOST=127.0.0.1
export OLLAMA_PORT=11434
export VLLM_BASE_URL=http://gpu01:8000
export VLLM_API_KEY=EMPTY          # 内部部署通常无需鉴权

# Agent 行为
export AGENT_MAX_RETRIES=2         # 每字段最大重试次数
export AGENT_DUMP_DIR=/tmp/debug   # Debug context 落盘目录
```

---

## 附录：关键设计决策说明

### A. 为什么保留 `llm_ollama.py`（不替换）？

保持 backward-compatibility：现有的 `extract_lab.py`、`extract_panel.py` 等都直接导入 `llm_ollama`。修改这些文件会带来不必要的风险。新的 `llm_client.py` 提供统一接口，新代码（agent/*.py）使用新接口，老代码继续用老接口，两者并存。

### B. PatientState 为什么用 TypedDict 而不是 dataclass？

LangGraph 要求 state 是 TypedDict 以支持增量更新（`dict.update()` 合并语义）。dataclass 在 LangGraph 中需要额外的 Reducer 配置，而 TypedDict 是零配置的默认选项。

### C. TOOL_REGISTRY 为什么在导入时构建？

所有 spec 都是 dataclass 常量，在 import 时就可以安全构建 registry。这样每次调用 `TOOL_REGISTRY[key](state)` 都是直接函数调用，没有任何运行时查找开销。

### D. fallback（无 langgraph）的意义？

本项目的核心价值是 ICU 数据抽取，而不是 LangGraph 框架本身。在没有安装 langgraph 的环境（如内网 GPU 服务器）中，`_run_without_langgraph()` 保证系统仍然可以完整运行，只是失去了 checkpoint 和流式输出能力。

---

*文档作者：Copilot Coding Agent，基于 deadyboy/docx_work 和 deadyboy/pdf_work 仓库深度分析生成。*
