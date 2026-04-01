from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


# Canonical doc_type codes used throughout the pipeline
DOC_COURSE = "course"   # 病程录 (time-anchored)
DOC_OP     = "op"       # 操作记录
DOC_BIG    = "big"      # 大病历
DOC_SURG   = "surg"     # 手术记录
DOC_DISCH  = "disch"    # 出院记录


@dataclass(frozen=True)
class DocSpec:
    doc_type: str
    filename: str


# Fixed filenames per patient folder
PATIENT_DOC_SPECS: List[DocSpec] = [
    DocSpec(DOC_COURSE, "病程录.docx"),
    DocSpec(DOC_OP,     "操作记录.docx"),
    DocSpec(DOC_BIG,    "大病历.docx"),
    DocSpec(DOC_SURG,   "手术记录.docx"),
    DocSpec(DOC_DISCH,  "出院记录.docx"),
]


def expected_patient_files() -> Dict[str, str]:
    """Return mapping doc_type -> filename."""
    return {s.doc_type: s.filename for s in PATIENT_DOC_SPECS}
