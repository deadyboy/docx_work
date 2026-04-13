"""Agent tools – thin wrappers that make extraction functions callable
from a LangGraph node or directly as stand-alone tools.

Design principles
-----------------
1. **Zero duplication**: every function here delegates to the existing
   extraction modules (``router.py``, ``extract_base.py``, etc.).  We add
   only the thin interface layer required by the agent framework.
2. **Uniform return contract**: every tool returns a ``ToolResult`` dict:

   .. code-block:: python

       {
           "ok": bool,          # True = success, False = failure / parse error
           "data": dict | list, # extracted payload (may be empty on failure)
           "error": str | None, # human-readable error message
       }

3. **Retry-friendly**: on parse failures the tool sets ``ok=False`` so the
   agent can decide to retry with an expanded context window or a different
   model without any special-case logic in the graph.
"""

from __future__ import annotations

import os
import traceback
from typing import Any, Dict, List, Optional, Tuple

from ..field_config import (
    LAB_FIELD_SPECS,
    PANEL_FIELD_SPECS,
    FLAGS_DEFAULT_SPEC,
    ECMO_BUNDLE_SPEC,
    LabFieldSpec,
    PanelFieldSpec,
    FlagsFieldSpec,
)
from ..router import (
    extract_lab_field,
    extract_panel_field,
    extract_flags_field,
    extract_ecmo_field,
    _sum_lab_values,
)
from ..extract_base import extract_patient_base_bundle


# ---------------------------------------------------------------------------
# ToolResult type alias
# ---------------------------------------------------------------------------

ToolResult = Dict[str, Any]


def _ok(data: Any) -> ToolResult:
    return {"ok": True, "data": data, "error": None}


def _fail(error: str, data: Any = None) -> ToolResult:
    return {"ok": False, "data": data or {}, "error": error}


def _has_parse_error(result: Any) -> bool:
    """Return True if the extraction result indicates a JSON parse failure."""
    if not isinstance(result, dict):
        return True
    if result.get("_parse_error"):
        return True
    # Flags / bundle: check nested data dict
    data = result.get("data")
    if isinstance(data, dict) and data.get("_parse_error"):
        return True
    return False


# ---------------------------------------------------------------------------
# Individual tool functions
# ---------------------------------------------------------------------------


def tool_extract_base(
    *,
    docs: Dict[str, Any],
    model: str,
    patient_dir: str,
    backend: str = "ollama",
) -> ToolResult:
    """Extract the 22 base fields (demographics, admission/discharge dates, etc.)."""
    os.environ.setdefault("LLM_BACKEND", backend)
    try:
        result = extract_patient_base_bundle(
            model=model, docs=docs, patient_dir=patient_dir
        )
        if _has_parse_error(result):
            return _fail(
                f"parse_error in base extraction: {result.get('_error', 'unknown')}",
                result,
            )
        return _ok(result)
    except Exception as e:
        return _fail(f"exception in base extraction: {traceback.format_exc(limit=3)}")


def tool_extract_lab(
    *,
    docs: Dict[str, Any],
    model: str,
    spec: LabFieldSpec,
    dump_contexts_dir: Optional[str] = None,
    backend: str = "ollama",
) -> ToolResult:
    """Extract time-series lab values for a single LabFieldSpec."""
    os.environ.setdefault("LLM_BACKEND", backend)
    try:
        result = extract_lab_field(
            model=model, docs=docs, spec=spec, dump_contexts_dir=dump_contexts_dir
        )
        if _has_parse_error(result):
            return _fail(
                f"parse_error in lab[{spec.key}]: {result.get('_error', 'unknown')}",
                result,
            )
        return _ok(result)
    except Exception as e:
        return _fail(
            f"exception in lab[{spec.key}]: {traceback.format_exc(limit=3)}"
        )


def tool_extract_panel(
    *,
    docs: Dict[str, Any],
    model: str,
    spec: PanelFieldSpec,
    dump_contexts_dir: Optional[str] = None,
    backend: str = "ollama",
) -> ToolResult:
    """Extract panel results (multi-analyte) for a single PanelFieldSpec."""
    os.environ.setdefault("LLM_BACKEND", backend)
    try:
        result = extract_panel_field(
            model=model, docs=docs, spec=spec, dump_contexts_dir=dump_contexts_dir
        )
        if _has_parse_error(result):
            return _fail(
                f"parse_error in panel[{spec.key}]: {result.get('_error', 'unknown')}",
                result,
            )
        return _ok(result)
    except Exception as e:
        return _fail(
            f"exception in panel[{spec.key}]: {traceback.format_exc(limit=3)}"
        )


def tool_extract_flags(
    *,
    docs: Dict[str, Any],
    model: str,
    spec: FlagsFieldSpec,
    dump_contexts_dir: Optional[str] = None,
    backend: str = "ollama",
) -> ToolResult:
    """Extract boolean flag fields (diagnoses, procedures, medications)."""
    os.environ.setdefault("LLM_BACKEND", backend)
    try:
        result = extract_flags_field(
            model=model, docs=docs, spec=spec, dump_contexts_dir=dump_contexts_dir
        )
        if _has_parse_error(result):
            return _fail(
                f"parse_error in flags: {result.get('_error', 'unknown')}",
                result,
            )
        return _ok(result)
    except Exception as e:
        return _fail(f"exception in flags: {traceback.format_exc(limit=3)}")


def tool_extract_ecmo(
    *,
    docs: Dict[str, Any],
    model: str,
    dump_contexts_dir: Optional[str] = None,
    backend: str = "ollama",
) -> ToolResult:
    """Extract ECMO episode data (on/off times, mode, outcome)."""
    os.environ.setdefault("LLM_BACKEND", backend)
    try:
        result = extract_ecmo_field(
            model=model,
            docs=docs,
            spec=ECMO_BUNDLE_SPEC,
            dump_contexts_dir=dump_contexts_dir,
        )
        if _has_parse_error(result):
            return _fail(
                f"parse_error in ecmo: {result.get('_error', 'unknown')}",
                result,
            )
        return _ok(result)
    except Exception as e:
        return _fail(f"exception in ecmo: {traceback.format_exc(limit=3)}")


def tool_compute_transfusion_totals(
    *,
    results: Dict[str, Any],
) -> ToolResult:
    """Post-process: sum raw transfusion volumes and cross-validate flag fields."""
    try:
        rbc_total = _sum_lab_values(results.get("红细胞输血提取", {}))
        plt_total = _sum_lab_values(results.get("血小板输血提取", {}))
        plasma_total = _sum_lab_values(results.get("血浆输血提取", {}))

        totals = {
            "输血情况红细胞总量": rbc_total,
            "输血情况血小板总量": plt_total,
            "输血情况血浆总量": plasma_total,
        }

        # Cross-validate FLAGS if available
        flags_result = results.get("FLAGS", {})
        if isinstance(flags_result, dict) and isinstance(
            flags_result.get("data"), dict
        ):
            flags_data = flags_result["data"]
            flags_evm = flags_result.get("evidence_map", {})

            def _sync(flag_key: str, total_val: Optional[str], label: str) -> None:
                if total_val and str(total_val) not in ("0", "0.0", "None"):
                    flags_data[flag_key] = "是"
                    flags_evm[flag_key] = (
                        f"【系统交叉验证】：已提取到明确的{label}量（{total_val}）"
                    )
                elif flags_data.get(flag_key) is None:
                    flags_data[flag_key] = "否"
                    flags_evm[flag_key] = (
                        f"【系统交叉验证】：未提取到具体的{label}量，且文本未明确提示"
                    )

            _sync("是否红细胞输血", rbc_total, "红细胞")
            _sync("是否血小板输血", plt_total, "血小板")
            _sync("是否血浆输血", plasma_total, "血浆")

        return _ok(totals)
    except Exception as e:
        return _fail(f"exception in transfusion totals: {traceback.format_exc(limit=3)}")


# ---------------------------------------------------------------------------
# Tool registry – maps field key → (tool_function, kwargs_builder)
# ---------------------------------------------------------------------------

# Each entry is:  field_key -> callable that accepts (state) -> ToolResult
# The graph calls these via ``TOOL_REGISTRY[field_key](state)``.

def _build_tool_registry() -> Dict[str, Any]:
    """Build the registry at import time so callers can introspect it."""
    registry: Dict[str, Any] = {}

    # Lab specs
    lab_by_key = {s.key: s for s in LAB_FIELD_SPECS}
    for spec in LAB_FIELD_SPECS:
        _spec = spec  # capture

        def _lab_tool(state: Dict[str, Any], _s: LabFieldSpec = _spec) -> ToolResult:
            return tool_extract_lab(
                docs=state["docs"],
                model=state["model"],
                spec=_s,
                dump_contexts_dir=state.get("dump_contexts_dir"),
                backend=state.get("backend", "ollama"),
            )

        registry[spec.key] = _lab_tool

    # Panel specs
    for spec in PANEL_FIELD_SPECS:
        _spec = spec

        def _panel_tool(
            state: Dict[str, Any], _s: PanelFieldSpec = _spec
        ) -> ToolResult:
            return tool_extract_panel(
                docs=state["docs"],
                model=state["model"],
                spec=_s,
                dump_contexts_dir=state.get("dump_contexts_dir"),
                backend=state.get("backend", "ollama"),
            )

        registry[spec.key] = _panel_tool

    # Flags
    def _flags_tool(state: Dict[str, Any]) -> ToolResult:
        return tool_extract_flags(
            docs=state["docs"],
            model=state["model"],
            spec=FLAGS_DEFAULT_SPEC,
            dump_contexts_dir=state.get("dump_contexts_dir"),
            backend=state.get("backend", "ollama"),
        )

    registry[FLAGS_DEFAULT_SPEC.key] = _flags_tool

    # ECMO
    def _ecmo_tool(state: Dict[str, Any]) -> ToolResult:
        ecmo_model = state.get("ecmo_model") or state["model"]
        return tool_extract_ecmo(
            docs=state["docs"],
            model=ecmo_model,
            dump_contexts_dir=state.get("dump_contexts_dir"),
            backend=state.get("backend", "ollama"),
        )

    registry[ECMO_BUNDLE_SPEC.key] = _ecmo_tool

    # Base info
    def _base_tool(state: Dict[str, Any]) -> ToolResult:
        return tool_extract_base(
            docs=state["docs"],
            model=state["model"],
            patient_dir=state["patient_dir"],
            backend=state.get("backend", "ollama"),
        )

    registry["基础信息与出入院"] = _base_tool

    # Transfusion totals (pure Python, no LLM)
    def _totals_tool(state: Dict[str, Any]) -> ToolResult:
        return tool_compute_transfusion_totals(results=state.get("results", {}))

    for key in ("输血情况红细胞总量", "输血情况血小板总量", "输血情况血浆总量"):
        registry[key] = _totals_tool

    return registry


TOOL_REGISTRY: Dict[str, Any] = _build_tool_registry()
