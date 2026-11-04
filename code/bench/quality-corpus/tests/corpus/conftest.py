"""Make corpus modules importable from the offline test suite."""

import sys
from pathlib import Path

CORPUS_ROOT = Path(__file__).resolve().parents[2] / "corpus"
if str(CORPUS_ROOT) not in sys.path:
    sys.path.insert(0, str(CORPUS_ROOT))
