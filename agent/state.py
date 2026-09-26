"""PatientState – shared state schema for the LangGraph agent.

All agent nodes read from and write to this TypedDict.  Every field has a
well-defined meaning so that nodes remain loosely coupled.

Design notes
------------
* We deliberately keep the state flat (no deeply nested objects) so that
  LangGraph's checkpointing / serialisation works without custom codecs.
* ``results`` stores the final extraction output keyed by field name.
* ``errors`` stores per-field error descriptions so the retry node can
  inspect them without re-running successful fields.
* ``retry_counts`` enforces a per-field retry budget (default cap = 2).
* ``messages`` is a human-readable audit trail that is also passed to the
  reflection node when it needs context about prior attempts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


class PatientState(TypedDict, total=False):
    # ── Input ──────────────────────────────────────────────────────────────
    patient_dir: str
    """Absolute path to the patient folder (contains *.docx files)."""

    docs: Dict[str, Any]
    """Parsed document blocks, keyed by doc_type (course/big/disch/op/surg)."""

    model: str
    """Default LLM model name for all extraction tasks."""

    ecmo_model: Optional[str]
    """Optional specialist model for ECMO extraction (e.g. a larger model)."""

    backend: str
    """LLM backend: 'ollama' or 'vllm'.  Defaults to 'ollama'."""

    dump_contexts_dir: Optional[str]
    """Directory for debug context dumps.  ``None`` disables dumping."""

    # ── Orchestration ──────────────────────────────────────────────────────
    pending_fields: List[str]
    """List of field keys that still need to be extracted."""

    retry_counts: Dict[str, int]
    """Number of retry attempts already made per field key."""

    max_retries: int
    """Maximum number of retries per field (default 2)."""

    # ── Results ────────────────────────────────────────────────────────────
    results: Dict[str, Any]
    """Extraction results keyed by field name, populated by extraction nodes."""

    errors: Dict[str, str]
    """Per-field error messages from failed extraction attempts."""

    # ── Status ─────────────────────────────────────────────────────────────
    status: str
    """Overall run status: 'pending' | 'running' | 'done' | 'failed'."""

    messages: List[str]
    """Human-readable audit trail (appended to by each node)."""


# ---------------------------------------------------------------------------
# Default initial state factory
# ---------------------------------------------------------------------------

# All fields that ``extract_all_default_fields`` produces.  The agent will
# iterate over this list so that new fields can be added simply by extending
# it – no graph wiring changes required.
DEFAULT_FIELD_KEYS: List[str] = [
    "基础信息与出入院",
    "PCT",
    "CRP",
    "APACHEII",
    "痰液真菌培养",
    "痰液药敏",
    "血培养",
    "红细胞输血提取",
    "血小板输血提取",
    "血浆输血提取",
    "急诊生化",
    "凝血功能DIC全套",
    "血常规",
    "血气分析",
    "FLAGS",
    "ECMO",
    # Post-processing derived fields (computed from the above)
    "输血情况红细胞总量",
    "输血情况血小板总量",
    "输血情况血浆总量",
]


def make_initial_state(
    patient_dir: str,
    model: str,
    ecmo_model: Optional[str] = None,
    backend: str = "ollama",
    dump_contexts_dir: Optional[str] = None,
    max_retries: int = 2,
) -> PatientState:
    """Create a fully initialised ``PatientState`` for a new run."""
    return PatientState(
        patient_dir=patient_dir,
        docs={},
        model=model,
        ecmo_model=ecmo_model,
        backend=backend,
        dump_contexts_dir=dump_contexts_dir,
        pending_fields=list(DEFAULT_FIELD_KEYS),
        retry_counts={},
        max_retries=max_retries,
        results={},
        errors={},
        status="pending",
        messages=[],
    )
