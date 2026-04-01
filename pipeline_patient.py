from __future__ import annotations
from typing import Dict, Any, Optional
from .debug_dump import dump_patient_blocks

from .load_patient import load_patient_docs
from .router import extract_all_default_fields

def run_one_patient(
    patient_dir: str,
    model: str,
    ecmo_model: Optional[str] = None, # 【新增】
    dump_blocks_out: Optional[str] = None,
    dump_contexts_dir: Optional[str] = None,
) -> Dict[str, Any]:
    docs, missing = load_patient_docs(patient_dir)

    if dump_blocks_out:
        dump_patient_blocks(docs, dump_blocks_out)

    fields = extract_all_default_fields(
        model=model,
        docs=docs,
        patient_dir=patient_dir,
        ecmo_model=ecmo_model,  # 【新增透传】
        dump_contexts_dir=dump_contexts_dir,
    )

    return {
        "patient_dir": patient_dir,
        "missing_docs": missing,
        **fields,
    }
