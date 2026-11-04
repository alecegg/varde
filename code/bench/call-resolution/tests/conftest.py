"""Configure imports for the bench harness, which is not an installed package."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
