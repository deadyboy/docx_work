from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


def load_router():
    path = Path(__file__).resolve().parents[1] / "agent" / "input_router.py"
    spec = importlib.util.spec_from_file_location("docx_agent_input_router_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


router = load_router()


class InputRouterContractTests(unittest.TestCase):
    def test_docx_directory_is_docx(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "病程录.docx").touch()
            result = router.route_input(d)
            self.assertEqual(result.input_type, "docx")
            self.assertTrue(result.has_canonical_docx_layout)

    def test_mixed_media_is_mixed(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "病程录.docx").touch()
            Path(d, "page_001.png").touch()
            self.assertEqual(router.detect_input_type(d), "mixed")

    def test_pdf_file_is_pdf(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "record.pdf")
            p.touch()
            self.assertEqual(router.detect_input_type(p), "pdf")


if __name__ == "__main__":
    unittest.main()
