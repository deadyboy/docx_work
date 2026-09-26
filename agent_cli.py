from __future__ import annotations

import sys
from pathlib import Path

# Allow direct execution from an arbitrary working directory while preserving
# the repository's package-relative imports.
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT.parent))

from docx_work.agent.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
