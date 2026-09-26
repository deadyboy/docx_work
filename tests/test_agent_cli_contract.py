from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def load_cli():
    # Load only the lightweight helpers without executing the real pipeline import.
    path = Path(__file__).resolve().parents[1] / "agent" / "cli.py"
    source = path.read_text(encoding="utf-8")
    source = source.replace("from .graph import run_patient_agent\n", "run_patient_agent = None\n")
    namespace = {"__name__": "docx_cli_contract_test", "__file__": str(path)}
    exec(compile(source, str(path), "exec"), namespace)
    return namespace


class CliEnvelopeTests(unittest.TestCase):
    def test_success_envelope(self):
        ns = load_cli()
        env = ns["build_envelope"]("/tmp/p1", {"status": "done", "results": {"PCT": 1}, "errors": {}})
        self.assertEqual(env["schema_version"], "icu-agent/v1")
        self.assertEqual(env["pipeline"], "docx")
        self.assertEqual(env["status"], "succeeded")

    def test_error_makes_partial(self):
        ns = load_cli()
        env = ns["build_envelope"]("/tmp/p1", {"status": "done", "results": {}, "errors": {"PCT": "x"}})
        self.assertEqual(env["status"], "partial")


if __name__ == "__main__":
    unittest.main()
