from __future__ import annotations

import os
from typing import Dict, List, Tuple

from .doc_registry import expected_patient_files, DOC_COURSE
from .docx_parse import docx_to_blocks, Block


def load_patient_docs(patient_dir: str) -> Tuple[Dict[str, List[Block]], Dict[str, str]]:
    """Load all available docs for a patient.

    Returns:
      docs: doc_type -> blocks
      missing: doc_type -> expected filename (for missing docs)
    """
    mapping = expected_patient_files()
    docs: Dict[str, List[Block]] = {}
    missing: Dict[str, str] = {}

    for doc_type, fname in mapping.items():
        path = os.path.join(patient_dir, fname)
        if not os.path.exists(path):
            missing[doc_type] = fname
            continue

        header_aware = (doc_type == DOC_COURSE)
        blocks = docx_to_blocks(path, doc_type=doc_type, header_aware=header_aware)
        docs[doc_type] = blocks

    return docs, missing
