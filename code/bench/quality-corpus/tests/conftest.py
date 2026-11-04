import sys
from pathlib import Path

QUALITY_CORPUS_ROOT = Path(__file__).resolve().parents[1]
if str(QUALITY_CORPUS_ROOT) not in sys.path:
    sys.path.insert(0, str(QUALITY_CORPUS_ROOT))
