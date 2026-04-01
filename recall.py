# from __future__ import annotations

# from typing import List, Tuple, Dict, Optional
# import re
# from collections import Counter
# from .docx_parse import Block


# def find_hits(blocks: List[Block], aliases: List[str]) -> List[int]:
#     """Keyword hit indices (list index, not block_id)."""
#     pats = [re.compile(re.escape(a), re.IGNORECASE) for a in aliases]
#     hits: List[int] = []
#     for i, b in enumerate(blocks):
#         if any(p.search(b.text) for p in pats):
#             hits.append(i)
#     return hits


# def build_windows(hit_idxs: List[int], n: int, k: int) -> List[Tuple[int, int]]:
#     return [(max(0, i - k), min(n - 1, i + k)) for i in hit_idxs]


# def merge_windows(wins: List[Tuple[int, int]], allow_adjacent: bool = True) -> List[Tuple[int, int]]:
#     """Merge overlapping (and optionally adjacent) windows."""
#     if not wins:
#         return []
#     wins = sorted(wins)
#     out = [wins[0]]
#     for s, e in wins[1:]:
#         ps, pe = out[-1]
#         if allow_adjacent:
#             overlap = s <= pe + 1
#         else:
#             overlap = s <= pe
#         if overlap:
#             out[-1] = (ps, max(pe, e))
#         else:
#             out.append((s, e))
#     return out


# def _pick_primary_anchor(anchors_in_order: List[str]) -> Optional[str]:
#     """Pick a stable primary anchor.

#     Use mode (most frequent) rather than first to reduce cross-anchor merge risk.
#     When tied, pick the earliest in appearance order.
#     """
#     if not anchors_in_order:
#         return None
#     counts = Counter(anchors_in_order)
#     maxc = max(counts.values())
#     candidates = {a for a, c in counts.items() if c == maxc}
#     for a in anchors_in_order:
#         if a in candidates:
#             return a
#     return anchors_in_order[0]


# def windows_to_contexts(
#     blocks: List[Block],
#     wins: List[Tuple[int, int]],
#     header_aware: bool,
#     doc_type: str,
# ) -> List[Dict]:
#     contexts: List[Dict] = []

#     for s, e in wins:
#         chunk_blocks = blocks[s : e + 1]

#         lines: List[str] = []
#         anchors_seq: List[str] = []  # keep duplicates for mode
#         anchors_unique: List[str] = []

#         for b in chunk_blocks:
#             prefix = f"[{doc_type}:B{b.block_id}]"
#             if header_aware and b.anchor_dt:
#                 prefix += f"({b.anchor_dt})"
#                 anchors_seq.append(b.anchor_dt)
#                 if b.anchor_dt not in anchors_unique:
#                     anchors_unique.append(b.anchor_dt)
#             lines.append(f"{prefix} {b.text}")

#         text_body = "\n".join(lines)

#         primary_anchor = _pick_primary_anchor(anchors_seq) if (header_aware and anchors_seq) else None

#         if header_aware and primary_anchor:
#             header_instruction = (
#                 f"[WINDOW_ANCHOR={primary_anchor}] "
#                 "规则：若行前缀自带(YYYY-...)时间则以该行为准；否则以WINDOW_ANCHOR为准。"
#             )
#             final_text = header_instruction + "\n" + text_body
#         else:
#             final_text = text_body

#         contexts.append(
#             {
#                 "doc_type": doc_type,
#                 "block_ids": [b.block_id for b in chunk_blocks],
#                 "text": final_text,
#                 "primary_anchor": primary_anchor,
#                 "anchors_in_window": anchors_unique,
#             }
#         )

#     return contexts


# def recall_in_one_doc(
#     blocks: List[Block],
#     doc_type: str,
#     aliases: List[str],
#     k: int,
#     header_aware: bool,
#     allow_adjacent_merge: bool,
# ) -> List[Dict]:
#     hits = find_hits(blocks, aliases)
#     wins = merge_windows(build_windows(hits, len(blocks), k), allow_adjacent=allow_adjacent_merge)
#     return windows_to_contexts(blocks, wins, header_aware=header_aware, doc_type=doc_type)


# def recall_patient(
#     docs: Dict[str, List[Block]],
#     aliases: List[str],
#     k_course: int = 2,
#     k_free: int = 1,
# ) -> List[Dict]:
#     """Patient-level recall across multiple docs.

#     - course: header_aware=True; merge without adjacency to reduce cross-anchor merge risk.
#     - others: header_aware=False; allow adjacent merge to reduce calls.
#     """
#     out: List[Dict] = []
#     for doc_type, blocks in docs.items():
#         if doc_type == "course":
#             out.extend(
#                 recall_in_one_doc(
#                     blocks,
#                     doc_type=doc_type,
#                     aliases=aliases,
#                     k=k_course,
#                     header_aware=True,
#                     allow_adjacent_merge=False,
#                 )
#             )
#         else:
#             out.extend(
#                 recall_in_one_doc(
#                     blocks,
#                     doc_type=doc_type,
#                     aliases=aliases,
#                     k=k_free,
#                     header_aware=False,
#                     allow_adjacent_merge=True,
#                 )
#             )
#     return out
from __future__ import annotations

from typing import List, Tuple, Dict, Optional
import re
from collections import Counter
from .docx_parse import Block


def find_hits(blocks: List[Block], aliases: List[str]) -> List[int]:
    """Keyword hit indices (list index, not block_id)."""
    pats = [re.compile(re.escape(a), re.IGNORECASE) for a in aliases]
    hits: List[int] = []
    for i, b in enumerate(blocks):
        if any(p.search(b.text) for p in pats):
            hits.append(i)
    return hits


def build_windows(hit_idxs: List[int], n: int, k: int) -> List[Tuple[int, int]]:
    return [(max(0, i - k), min(n - 1, i + k)) for i in hit_idxs]


def merge_windows(
    wins: List[Tuple[int, int]], 
    allow_adjacent: bool = True,
    max_window_size: int = 15  # 【新增】最大窗口块数熔断阈值
) -> List[Tuple[int, int]]:
    """Merge overlapping (and optionally adjacent) windows, with a size limit breaker."""
    if not wins:
        return []
    
    wins = sorted(wins)
    out = [wins[0]]
    
    for s, e in wins[1:]:
        ps, pe = out[-1]
        
        # 判断是否在物理上存在重叠或相邻
        if allow_adjacent:
            overlap = s <= pe + 1
        else:
            overlap = s <= pe
            
        if overlap:
            # 【核心熔断机制】：前瞻性计算合并后的大小
            proposed_pe = max(pe, e)
            proposed_size = proposed_pe - ps + 1
            
            if proposed_size <= max_window_size:
                # 安全，执行合并
                out[-1] = (ps, proposed_pe)
            else:
                # 危险，触发熔断！即使物理重叠也不再合并，将当前窗口作为独立窗口追加
                out.append((s, e))
        else:
            out.append((s, e))
            
    return out


def _pick_primary_anchor(anchors_in_order: List[str]) -> Optional[str]:
    """Pick a stable primary anchor.

    Use mode (most frequent) rather than first to reduce cross-anchor merge risk.
    When tied, pick the earliest in appearance order.
    """
    if not anchors_in_order:
        return None
    counts = Counter(anchors_in_order)
    maxc = max(counts.values())
    candidates = {a for a, c in counts.items() if c == maxc}
    for a in anchors_in_order:
        if a in candidates:
            return a
    return anchors_in_order[0]


def windows_to_contexts(
    blocks: List[Block],
    wins: List[Tuple[int, int]],
    header_aware: bool,
    doc_type: str,
) -> List[Dict]:
    contexts: List[Dict] = []

    for s, e in wins:
        chunk_blocks = blocks[s : e + 1]

        lines: List[str] = []
        anchors_seq: List[str] = []  # keep duplicates for mode
        anchors_unique: List[str] = []

        for b in chunk_blocks:
            prefix = f"[{doc_type}:B{b.block_id}]"
            if header_aware and b.anchor_dt:
                prefix += f"({b.anchor_dt})"
                anchors_seq.append(b.anchor_dt)
                if b.anchor_dt not in anchors_unique:
                    anchors_unique.append(b.anchor_dt)
            lines.append(f"{prefix} {b.text}")

        text_body = "\n".join(lines)

        primary_anchor = _pick_primary_anchor(anchors_seq) if (header_aware and anchors_seq) else None

        if header_aware and primary_anchor:
            header_instruction = (
                f"[WINDOW_ANCHOR={primary_anchor}] "
                "规则：若行前缀自带(YYYY-...)时间则以该行为准；否则以WINDOW_ANCHOR为准。"
            )
            final_text = header_instruction + "\n" + text_body
        else:
            final_text = text_body

        contexts.append(
            {
                "doc_type": doc_type,
                "block_ids": [b.block_id for b in chunk_blocks],
                "text": final_text,
                "primary_anchor": primary_anchor,
                "anchors_in_window": anchors_unique,
            }
        )

    return contexts


def recall_in_one_doc(
    blocks: List[Block],
    doc_type: str,
    aliases: List[str],
    k: int,
    header_aware: bool,
    allow_adjacent_merge: bool,
    max_window_size: int, # 【新增】透传参数
) -> List[Dict]:
    hits = find_hits(blocks, aliases)
    wins = merge_windows(
        build_windows(hits, len(blocks), k), 
        allow_adjacent=allow_adjacent_merge,
        max_window_size=max_window_size # 【新增】应用阈值
    )
    return windows_to_contexts(blocks, wins, header_aware=header_aware, doc_type=doc_type)


def recall_patient(
    docs: Dict[str, List[Block]],
    aliases: List[str],
    k_course: int = 2,
    k_free: int = 1,
    max_window_size: int = 10, # 【新增】提供全局控制，默认限制为最大 15 个 Block
) -> List[Dict]:
    """Patient-level recall across multiple docs.

    - course: header_aware=True; merge without adjacency to reduce cross-anchor merge risk.
    - others: header_aware=False; allow adjacent merge to reduce calls.
    """
    out: List[Dict] = []
    for doc_type, blocks in docs.items():
        if doc_type == "course":
            out.extend(
                recall_in_one_doc(
                    blocks,
                    doc_type=doc_type,
                    aliases=aliases,
                    k=k_course,
                    header_aware=True,
                    allow_adjacent_merge=False,
                    max_window_size=max_window_size, # 【新增】
                )
            )
        else:
            out.extend(
                recall_in_one_doc(
                    blocks,
                    doc_type=doc_type,
                    aliases=aliases,
                    k=k_free,
                    header_aware=False,
                    allow_adjacent_merge=True,
                    max_window_size=max_window_size, # 【新增】
                )
            )
    return out