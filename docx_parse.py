from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from docx import Document
import re


@dataclass
class Block:
    block_id: int
    doc_type: str
    text: str
    anchor_dt: Optional[str] = None  # ISO: YYYY-MM-DD HH:MM:SS for course doc


_ws_re = re.compile(r"[ \t\u3000]+")

# Course header regex: supports
# - YYYY-MM-DD
# - YYYY-MM-DD HH:MM
# - YYYY-MM-DD HH:MM:SS
# and also '/' as date separator.
# Example:
#   2019-12-04 12:42             危急值处理记录
#   2019/12/04 12:42
COURSE_DT_RE = re.compile(
    r"^\s*(?P<date>20\d{2}[-/]\d{2}[-/]\d{2})(?:\s+(?P<hh>\d{2}):(?P<mm>\d{2})(?::(?P<ss>\d{2}))?)?\b"
)


def normalize_text(s: str) -> str:
    s = s.replace("\r", "\n")
    s = _ws_re.sub(" ", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def _to_iso_dt(date: str, hh: Optional[str], mm: Optional[str], ss: Optional[str]) -> str:
    """Normalize to ISO-ish datetime: YYYY-MM-DD HH:MM:SS.

    If time is missing, default to 00:00:00.
    If seconds are missing, default to :00.
    """
    date = date.replace("/", "-")
    if hh is None or mm is None:
        return f"{date} 00:00:00"
    ss = ss if ss is not None else "00"
    return f"{date} {hh}:{mm}:{ss}"


def docx_to_blocks(docx_path: str, doc_type: str, header_aware: bool = False) -> List[Block]:
    """Read a docx into a list of Blocks.

    - For free-text docs: each paragraph becomes one Block; anchor_dt stays None.
    - For course doc (header_aware=True): detect datetime headers and propagate anchor_dt to subsequent blocks.

    IMPORTANT: We intentionally do *not* rely on regex to parse all medical content.
    Regex here is only for *structural anchoring* (time headers).
    """
    doc = Document(docx_path)
    blocks: List[Block] = []
    bid = 0

    current_anchor: Optional[str] = None

    for p in doc.paragraphs:
        raw = p.text
        t = normalize_text(raw)
        if not t:
            continue

        anchor_dt = None
        if header_aware:
            m = COURSE_DT_RE.match(t)
            if m:
                current_anchor = _to_iso_dt(
                    m.group("date"),
                    m.group("hh"),
                    m.group("mm"),
                    m.group("ss"),
                )
            anchor_dt = current_anchor

        blocks.append(Block(block_id=bid, doc_type=doc_type, text=t, anchor_dt=anchor_dt))
        bid += 1

    return blocks


def blocks_to_plaintext(blocks: List[Block]) -> str:
    lines = []
    for b in blocks:
        pref = f"[{b.doc_type}:B{b.block_id}]"
        if b.anchor_dt:
            pref += f"({b.anchor_dt})"
        lines.append(f"{pref} {b.text}")
    return "\n".join(lines)
