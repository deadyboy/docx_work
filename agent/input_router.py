"""Input router – automatic detection and dispatching of input types.

The agent framework supports two distinct pipeline modes:

1. **DOCX mode** (``docx_work``)
   Input: a directory containing ``*.docx`` files (one per document type).
   Pipeline: DOCX parse → recall → LLM extract → QC.

2. **Image/PDF mode** (``pdf_work``)
   Input: a directory (or a single file) containing ``*.png`` / ``*.jpg`` /
   ``*.pdf`` ICU nursing record images.
   Pipeline: image slice → classify → multimodal LLM extract → merge.

``detect_input_type()`` inspects the path and returns one of the string
literals ``"docx"`` / ``"image"`` / ``"pdf"`` / ``"mixed"`` / ``"unknown"``.

``route_input()`` returns a ``InputRouteResult`` carrying the detected type
and pre-computed metadata that downstream code can use without re-scanning.

Why does this matter for agents?
---------------------------------
A top-level orchestrator agent receiving a patient folder should be able to:

* Decide *which* sub-pipeline to invoke (DOCX extractor vs vision extractor).
* Handle mixed inputs (e.g. some patients have DOCX files AND nursing-record
  images) by spawning both sub-agents in parallel.
* Reject unsupported inputs early with a clear error message.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DOCX_EXTENSIONS = {".docx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}
PDF_EXTENSIONS = {".pdf"}

# The canonical DOCX filenames used by docx_work (from doc_registry.py)
CANONICAL_DOCX_NAMES = {
    "病程录.docx",
    "操作记录.docx",
    "大病历.docx",
    "手术记录.docx",
    "出院记录.docx",
}

InputType = Literal["docx", "image", "pdf", "mixed", "unknown"]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class InputRouteResult:
    """Result of automatic input type detection."""

    input_type: InputType
    """Primary type detected."""

    path: str
    """Absolute path that was inspected."""

    docx_files: List[str] = field(default_factory=list)
    """DOCX files found (absolute paths)."""

    image_files: List[str] = field(default_factory=list)
    """Image files found (absolute paths)."""

    pdf_files: List[str] = field(default_factory=list)
    """PDF files found (absolute paths)."""

    has_canonical_docx_layout: bool = False
    """True when the directory matches the expected docx_work folder layout."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Extra metadata (e.g. file counts, detected record types)."""

    error: Optional[str] = None
    """Set when detection failed or the path does not exist."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_input_type(path: Union[str, Path]) -> InputType:
    """Return the dominant input type for *path*.

    Parameters
    ----------
    path:
        A file or directory path to inspect.

    Returns
    -------
    InputType
        One of ``"docx"``, ``"image"``, ``"pdf"``, ``"mixed"``, ``"unknown"``.
    """
    result = route_input(path)
    return result.input_type


def route_input(path: Union[str, Path]) -> InputRouteResult:
    """Fully inspect *path* and return a rich ``InputRouteResult``.

    The detection logic is:

    1. If the path doesn't exist → ``"unknown"`` with an error.
    2. If the path is a single file → determined by extension.
    3. If the path is a directory:
       a. Collect all files by extension.
       b. Check for canonical docx_work layout (known filenames).
       c. If only DOCX → ``"docx"``.
       d. If only images → ``"image"``.
       e. If only PDFs → ``"pdf"``.
       f. If both DOCX and images/PDFs → ``"mixed"``.
       g. Otherwise → ``"unknown"``.
    """
    path = Path(path).resolve()
    abs_str = str(path)

    if not path.exists():
        return InputRouteResult(
            input_type="unknown",
            path=abs_str,
            error=f"Path does not exist: {abs_str}",
        )

    # ── Single file ──────────────────────────────────────────────────────
    if path.is_file():
        ext = path.suffix.lower()
        if ext in DOCX_EXTENSIONS:
            return InputRouteResult(
                input_type="docx",
                path=abs_str,
                docx_files=[abs_str],
            )
        if ext in IMAGE_EXTENSIONS:
            return InputRouteResult(
                input_type="image",
                path=abs_str,
                image_files=[abs_str],
            )
        if ext in PDF_EXTENSIONS:
            return InputRouteResult(
                input_type="pdf",
                path=abs_str,
                pdf_files=[abs_str],
            )
        return InputRouteResult(
            input_type="unknown",
            path=abs_str,
            error=f"Unsupported file extension: {path.suffix}",
        )

    # ── Directory ────────────────────────────────────────────────────────
    docx_files: List[str] = []
    image_files: List[str] = []
    pdf_files: List[str] = []

    for entry in sorted(path.iterdir()):
        if not entry.is_file():
            continue
        ext = entry.suffix.lower()
        if ext in DOCX_EXTENSIONS:
            docx_files.append(str(entry))
        elif ext in IMAGE_EXTENSIONS:
            image_files.append(str(entry))
        elif ext in PDF_EXTENSIONS:
            pdf_files.append(str(entry))

    # Check for canonical docx_work layout
    found_names = {Path(f).name for f in docx_files}
    has_canonical = bool(found_names & CANONICAL_DOCX_NAMES)

    has_docx = bool(docx_files)
    has_img = bool(image_files)
    has_pdf = bool(pdf_files)

    if has_docx and not has_img and not has_pdf:
        input_type: InputType = "docx"
    elif has_img and not has_docx and not has_pdf:
        input_type = "image"
    elif has_pdf and not has_docx and not has_img:
        input_type = "pdf"
    elif (has_docx or has_pdf) and has_img:
        input_type = "mixed"
    elif has_docx and has_pdf:
        input_type = "mixed"
    else:
        input_type = "unknown"

    return InputRouteResult(
        input_type=input_type,
        path=abs_str,
        docx_files=docx_files,
        image_files=image_files,
        pdf_files=pdf_files,
        has_canonical_docx_layout=has_canonical,
        metadata={
            "n_docx": len(docx_files),
            "n_images": len(image_files),
            "n_pdfs": len(pdf_files),
            "canonical_files_found": sorted(found_names & CANONICAL_DOCX_NAMES),
        },
    )


# ---------------------------------------------------------------------------
# Convenience: classify a batch directory
# ---------------------------------------------------------------------------


def classify_batch_directory(
    batch_dir: Union[str, Path],
) -> Dict[str, InputRouteResult]:
    """Scan every sub-directory of *batch_dir* and classify each one.

    Returns a mapping ``patient_id → InputRouteResult``.

    This is intended for the top-level orchestrator that processes many
    patients at once and needs to dispatch each one to the correct pipeline.

    Example
    -------
    ::

        from docx_work.agent.input_router import classify_batch_directory

        results = classify_batch_directory("/data/all_patients")
        for pid, r in results.items():
            if r.input_type == "docx":
                # dispatch to docx pipeline
                ...
            elif r.input_type == "image":
                # dispatch to vision pipeline
                ...
    """
    batch_dir = Path(batch_dir).resolve()
    out: Dict[str, InputRouteResult] = {}
    for entry in sorted(batch_dir.iterdir()):
        if entry.is_dir():
            out[entry.name] = route_input(entry)
    return out
