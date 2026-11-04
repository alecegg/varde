import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
RATERS_DIR = REPO_ROOT / "code" / "bench" / "quality-corpus" / "raters"
PROMPT_FILES = {
    "lens-0-neutral-baseline.md",
    "lens-1-clean-code.md",
    "lens-2-philosophy-of-software-design.md",
    "lens-3-modern-practice-cognitive-load.md",
}


def test_rater_prompt_hashes_match_prompt_contents() -> None:
    actual_files = {path.name for path in RATERS_DIR.glob("lens-*.md")}
    assert actual_files == PROMPT_FILES

    expected = {
        filename: hashlib.sha256((RATERS_DIR / filename).read_bytes()).hexdigest()
        for filename in PROMPT_FILES
    }
    actual = {}
    for line in (RATERS_DIR / "hashes.txt").read_text(encoding="utf-8").splitlines():
        digest, filename = line.split(maxsplit=1)
        assert filename not in actual
        actual[filename] = digest

    assert actual == expected
