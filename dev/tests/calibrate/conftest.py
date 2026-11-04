import sys
from pathlib import Path

DEV_SRC = Path(__file__).resolve().parents[2] / "src"
if str(DEV_SRC) not in sys.path:
    sys.path.insert(0, str(DEV_SRC))
