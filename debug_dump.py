# src/debug_dump.py
from __future__ import annotations
from typing import Dict, List, Any, Optional
import os

from .docx_parse import Block, blocks_to_plaintext

def dump_patient_blocks(docs: Dict[str, List[Block]], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for doc_type in sorted(docs.keys()):
            blocks = docs[doc_type]
            f.write("=" * 80 + "\n")
            f.write(f"[DOC_TYPE={doc_type}] blocks={len(blocks)}\n")
            f.write("=" * 80 + "\n")
            f.write(blocks_to_plaintext(blocks))
            f.write("\n\n")

def dump_contexts(contexts: List[Dict[str, Any]], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for i, ctx in enumerate(contexts):
            f.write("=" * 80 + "\n")
            f.write(f"[CTX#{i}] doc_type={ctx.get('doc_type')} block_ids={ctx.get('block_ids')}\n")
            f.write(f"primary_anchor={ctx.get('primary_anchor')} anchors_in_window={ctx.get('anchors_in_window')}\n")
            f.write("=" * 80 + "\n")
            f.write(ctx.get("text", ""))
            f.write("\n\n")
