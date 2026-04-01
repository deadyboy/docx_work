from __future__ import annotations

from typing import Dict, Any

from .docx_parse import docx_to_blocks
from .recall import recall_in_one_doc
from .extract_lab import extract_lab_items


def run_one_docx(docx_path: str, model: str, doc_type: str = "course") -> Dict[str, Any]:
    header_aware = (doc_type == "course")
    blocks = docx_to_blocks(docx_path, doc_type=doc_type, header_aware=header_aware)

    pct_ctxs = recall_in_one_doc(
        blocks,
        doc_type=doc_type,
        aliases=["PCT", "降钙素原"],
        k=2 if header_aware else 1,
        header_aware=header_aware,
        allow_adjacent_merge=not header_aware,
    )
    pct_res = extract_lab_items(
        model=model,
        lab_name="PCT/降钙素原",
        aliases=["PCT", "降钙素原"],
        unit_candidates=["ng/ml", "ng/mL"],
        contexts=pct_ctxs,
        max_items=50,
    )

    crp_ctxs = recall_in_one_doc(
        blocks,
        doc_type=doc_type,
        aliases=["CRP", "C反应蛋白", "超敏C反应蛋白"],
        k=2 if header_aware else 1,
        header_aware=header_aware,
        allow_adjacent_merge=not header_aware,
    )
    crp_res = extract_lab_items(
        model=model,
        lab_name="CRP/C反应蛋白",
        aliases=["CRP", "C反应蛋白", "超敏C反应蛋白"],
        unit_candidates=["mg/L", "mg/l"],
        contexts=crp_ctxs,
        max_items=50,
    )

    return {"PCT": pct_res, "CRP": crp_res}
