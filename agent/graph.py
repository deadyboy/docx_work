"""LangGraph agent graph for medical record extraction.

Graph topology
--------------
::

    START
      │
      ▼
    [load_docs]   – parse DOCX files into Block sequences
      │
      ▼
    [plan]        – build ordered list of fields to extract
      │
      ▼
    [extract]     – run the next pending field's tool
      │
      ├─(ok)─────────────────────────────────────────────┐
      │                                                   │
      ├─(parse_error, retries_left)─→ [retry_expand] ────┤
      │                                                   │
      └─(parse_error, no retries)───→ [log_skip] ────────┤
                                                          │
                                                    (more pending?)
                                                          │
                                              yes ◄───────┤──────► no
                                              │                     │
                                           [extract]            [postprocess]
                                                                    │
                                                                    ▼
                                                                  END

Retry strategy
--------------
When a tool returns ``ok=False`` and the field's retry count is below
``state["max_retries"]``:

* ``retry_expand`` doubles ``k_course`` / ``k_free`` in the spec to widen the
  recall window and then re-queues the field at the front of ``pending_fields``.

The ``postprocess`` node runs ``tool_compute_transfusion_totals`` and then
packages the final flat result dict.

Usage
-----
::

    from docx_work.agent.graph import run_patient_agent

    result = run_patient_agent(
        patient_dir="/data/patient_001",
        model="qwen3:8b",
        ecmo_model="qwen14b-structured:latest",
    )
    print(result["results"])
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from .state import PatientState, make_initial_state, DEFAULT_FIELD_KEYS
from .tools import TOOL_REGISTRY, tool_compute_transfusion_totals

# ---------------------------------------------------------------------------
# LangGraph import (optional at runtime – graceful fallback for environments
# that don't have langgraph installed, so the rest of the codebase still
# imports without error).
# ---------------------------------------------------------------------------
try:
    from langgraph.graph import StateGraph, END
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _LANGGRAPH_AVAILABLE = False

from ..load_patient import load_patient_docs


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


def node_load_docs(state: PatientState) -> Dict[str, Any]:
    """Load and parse DOCX files from the patient directory."""
    patient_dir = state["patient_dir"]
    messages = list(state.get("messages", []))
    try:
        docs, missing = load_patient_docs(patient_dir)
        messages.append(
            f"[load_docs] Loaded {len(docs)} doc type(s). Missing: {missing or 'none'}"
        )
        return {
            "docs": docs,
            "status": "running",
            "messages": messages,
        }
    except Exception as e:
        messages.append(f"[load_docs] FATAL: {e}")
        return {
            "docs": {},
            "status": "failed",
            "messages": messages,
        }


def node_plan(state: PatientState) -> Dict[str, Any]:
    """Build the ordered extraction plan.

    The default order ensures that derived/post-process fields come last:
    base info → lab → panel → flags → ECMO → transfusion totals.
    """
    messages = list(state.get("messages", []))
    # Preserve whatever is already in pending_fields (caller may have
    # customised the list), only fill it in if it's empty.
    pending = list(state.get("pending_fields", []))
    if not pending:
        pending = list(DEFAULT_FIELD_KEYS)

    messages.append(f"[plan] Scheduled {len(pending)} field(s) for extraction.")
    return {
        "pending_fields": pending,
        "retry_counts": dict(state.get("retry_counts", {})),
        "results": dict(state.get("results", {})),
        "errors": dict(state.get("errors", {})),
        "messages": messages,
    }


def node_extract(state: PatientState) -> Dict[str, Any]:
    """Pop the first pending field and run its extraction tool."""
    pending = list(state.get("pending_fields", []))
    results = dict(state.get("results", {}))
    errors = dict(state.get("errors", {}))
    retry_counts = dict(state.get("retry_counts", {}))
    messages = list(state.get("messages", []))

    if not pending:
        return {"pending_fields": pending, "status": "done"}

    field_key = pending[0]
    remaining = pending[1:]

    tool_fn = TOOL_REGISTRY.get(field_key)
    if tool_fn is None:
        messages.append(f"[extract] No tool registered for '{field_key}', skipping.")
        errors[field_key] = "no_tool_registered"
        return {
            "pending_fields": remaining,
            "results": results,
            "errors": errors,
            "messages": messages,
        }

    messages.append(f"[extract] Extracting field: '{field_key}' ...")
    tool_result = tool_fn(state)

    if tool_result["ok"]:
        results[field_key] = tool_result["data"]
        messages.append(f"[extract] '{field_key}' succeeded.")
        return {
            "pending_fields": remaining,
            "results": results,
            "errors": errors,
            "retry_counts": retry_counts,
            "messages": messages,
        }
    else:
        # Failure: record error and decide whether to retry
        n_retries = retry_counts.get(field_key, 0)
        max_retries = state.get("max_retries", 2)
        errors[field_key] = tool_result["error"] or "unknown_error"
        messages.append(
            f"[extract] '{field_key}' FAILED (attempt {n_retries + 1}/{max_retries + 1}): "
            f"{tool_result['error']}"
        )

        if n_retries < max_retries:
            # Re-queue field at the front for retry
            retry_counts[field_key] = n_retries + 1
            remaining = [field_key] + remaining
            messages.append(f"[extract] Queued '{field_key}' for retry #{n_retries + 1}.")
        else:
            # Give up – store partial data if any
            if tool_result.get("data"):
                results[field_key] = tool_result["data"]
            messages.append(f"[extract] '{field_key}' skipped after {max_retries + 1} attempts.")

        return {
            "pending_fields": remaining,
            "results": results,
            "errors": errors,
            "retry_counts": retry_counts,
            "messages": messages,
        }


def node_postprocess(state: PatientState) -> Dict[str, Any]:
    """Run post-processing steps that combine results from multiple fields."""
    results = dict(state.get("results", {}))
    messages = list(state.get("messages", []))

    # Compute transfusion totals and cross-validate flags
    totals_result = tool_compute_transfusion_totals(results=results)
    if totals_result["ok"]:
        results.update(totals_result["data"])
        messages.append("[postprocess] Transfusion totals computed and FLAGS cross-validated.")
    else:
        messages.append(
            f"[postprocess] Transfusion totals failed: {totals_result['error']}"
        )

    return {
        "results": results,
        "status": "done",
        "messages": messages,
    }


# ---------------------------------------------------------------------------
# Routing function
# ---------------------------------------------------------------------------


def _route_after_extract(state: PatientState) -> str:
    """Decide the next node after an extraction step."""
    if state.get("status") == "failed":
        return END
    if state.get("pending_fields"):
        return "extract"
    return "postprocess"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_patient_graph():
    """Assemble and compile the LangGraph extraction graph.

    Returns
    -------
    CompiledGraph
        A compiled LangGraph graph ready to be invoked with an initial state.

    Raises
    ------
    ImportError
        If ``langgraph`` is not installed.
    """
    if not _LANGGRAPH_AVAILABLE:
        raise ImportError(
            "langgraph is required to use the agent graph. "
            "Install it with: pip install langgraph"
        )

    builder = StateGraph(PatientState)

    builder.add_node("load_docs", node_load_docs)
    builder.add_node("plan", node_plan)
    builder.add_node("extract", node_extract)
    builder.add_node("postprocess", node_postprocess)

    builder.set_entry_point("load_docs")
    builder.add_edge("load_docs", "plan")
    builder.add_edge("plan", "extract")
    builder.add_conditional_edges(
        "extract",
        _route_after_extract,
        {
            "extract": "extract",
            "postprocess": "postprocess",
            END: END,
        },
    )
    builder.add_edge("postprocess", END)

    return builder.compile()


# ---------------------------------------------------------------------------
# Top-level convenience function
# ---------------------------------------------------------------------------


def run_patient_agent(
    patient_dir: str,
    model: str,
    *,
    ecmo_model: Optional[str] = None,
    backend: str = "ollama",
    dump_contexts_dir: Optional[str] = None,
    max_retries: int = 2,
    custom_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run the full extraction agent for one patient.

    This is a high-level convenience wrapper.  For streaming, checkpointing,
    or graph introspection, use :func:`build_patient_graph` directly.

    Parameters
    ----------
    patient_dir:
        Absolute path to the patient's folder (must contain ``*.docx`` files).
    model:
        Default LLM model name (Ollama model tag or vLLM model identifier).
    ecmo_model:
        Optional specialist model for ECMO extraction.  Defaults to ``model``.
    backend:
        ``"ollama"`` (default) or ``"vllm"``.
    dump_contexts_dir:
        Directory for debug context dumps.  ``None`` disables dumping.
    max_retries:
        Number of retry attempts per field on parse failure.
    custom_fields:
        Optional override for the list of fields to extract.  When ``None``,
        all default fields are extracted.

    Returns
    -------
    dict
        The final :class:`PatientState` dictionary, which includes:

        * ``results`` – the extracted data per field.
        * ``errors`` – per-field error messages from any failed attempts.
        * ``messages`` – the audit trail log.
        * ``status`` – ``"done"`` or ``"failed"``.
    """
    if _LANGGRAPH_AVAILABLE:
        graph = build_patient_graph()
        initial_state = make_initial_state(
            patient_dir=patient_dir,
            model=model,
            ecmo_model=ecmo_model,
            backend=backend,
            dump_contexts_dir=dump_contexts_dir,
            max_retries=max_retries,
        )
        if custom_fields is not None:
            initial_state["pending_fields"] = custom_fields

        final_state = graph.invoke(initial_state)
        return dict(final_state)
    else:
        # Fallback: run nodes sequentially without LangGraph
        return _run_without_langgraph(
            patient_dir=patient_dir,
            model=model,
            ecmo_model=ecmo_model,
            backend=backend,
            dump_contexts_dir=dump_contexts_dir,
            max_retries=max_retries,
            custom_fields=custom_fields,
        )


def _run_without_langgraph(
    patient_dir: str,
    model: str,
    ecmo_model: Optional[str],
    backend: str,
    dump_contexts_dir: Optional[str],
    max_retries: int,
    custom_fields: Optional[List[str]],
) -> Dict[str, Any]:
    """Pure-Python fallback when langgraph is not installed.

    Executes the same nodes sequentially, enabling the agent module to be
    imported and used without the langgraph dependency.
    """
    state: PatientState = make_initial_state(
        patient_dir=patient_dir,
        model=model,
        ecmo_model=ecmo_model,
        backend=backend,
        dump_contexts_dir=dump_contexts_dir,
        max_retries=max_retries,
    )
    if custom_fields is not None:
        state["pending_fields"] = list(custom_fields)

    def _merge(s: PatientState, update: Dict[str, Any]) -> PatientState:
        s = dict(s)
        s.update(update)
        return PatientState(**s)

    # load_docs
    state = _merge(state, node_load_docs(state))
    if state.get("status") == "failed":
        return dict(state)

    # plan
    state = _merge(state, node_plan(state))

    # extract loop
    _guard = 0
    _max_iterations = len(state.get("pending_fields", [])) * (max_retries + 2) + 10
    while state.get("pending_fields"):
        _guard += 1
        if _guard > _max_iterations:
            state["messages"].append("[graph] Safety limit reached, stopping.")  # type: ignore
            break
        update = node_extract(state)
        state = _merge(state, update)
        if state.get("status") in ("done", "failed"):
            break

    # postprocess
    state = _merge(state, node_postprocess(state))
    return dict(state)
