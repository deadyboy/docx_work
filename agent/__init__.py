"""Agent package for medical record extraction.

This package provides a LangGraph-based agent that wraps the existing
extraction pipeline, enabling:

* Dynamic field-level routing and orchestration
* Unified patient state management
* Automatic retry / reflection on parse failures
* Input type detection (DOCX directory vs PDF/image)
* Unified LLM backend switching (Ollama ↔ vLLM)

Quick-start
-----------
::

    from docx_work.agent import run_patient_agent

    result = run_patient_agent(
        patient_dir="/data/patient_001",
        model="qwen3:8b",
    )
"""

from .graph import run_patient_agent, build_patient_graph
from .input_router import detect_input_type, route_input
from .state import PatientState

__all__ = [
    "run_patient_agent",
    "build_patient_graph",
    "detect_input_type",
    "route_input",
    "PatientState",
]
