from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .graph import run_patient_agent

SCHEMA_VERSION = "icu-agent/v1"


def _status_from_state(state: Dict[str, Any]) -> str:
    if state.get("status") == "failed":
        return "failed"
    return "partial" if state.get("errors") else "succeeded"


def build_envelope(input_path: str, state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "pipeline": "docx",
        "status": _status_from_state(state),
        "input_path": os.path.abspath(input_path),
        "result": state.get("results", {}),
        "errors": state.get("errors", {}),
        "meta": {
            "retry_counts": state.get("retry_counts", {}),
            "messages": state.get("messages", []),
        },
    }


def write_envelope(path: str | Path, envelope: Dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="DOCX ICU Agent adapter")
    parser.add_argument("input_path")
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--ecmo-model", default=None)
    parser.add_argument("--backend", choices=["ollama", "vllm"], default="ollama")
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--fields", default=None, help="Comma-separated field keys")
    parser.add_argument("--result-json", required=True)
    args = parser.parse_args(argv)

    custom_fields = None
    if args.fields:
        custom_fields = [x.strip() for x in args.fields.split(",") if x.strip()]

    try:
        state = run_patient_agent(
            patient_dir=args.input_path,
            model=args.model,
            ecmo_model=args.ecmo_model,
            backend=args.backend,
            max_retries=args.max_retries,
            custom_fields=custom_fields,
        )
        envelope = build_envelope(args.input_path, state)
    except Exception as exc:
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "pipeline": "docx",
            "status": "failed",
            "input_path": os.path.abspath(args.input_path),
            "result": {},
            "errors": {"__exception": f"{type(exc).__name__}: {exc}"},
            "meta": {},
        }

    write_envelope(args.result_json, envelope)
    return 0 if envelope["status"] in {"succeeded", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
