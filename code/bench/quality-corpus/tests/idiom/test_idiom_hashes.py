import hashlib
import re
from itertools import pairwise
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
IDIOM_DIR = REPO_ROOT / "code" / "bench" / "quality-corpus" / "idiom"
LANGUAGES = {"python", "typescript", "java", "go", "rust", "csharp", "cpp"}
HEADINGS = ("## Idiomatic patterns", "## Not a defect by itself")
PROHIBITED = re.compile(r"\b(?:split|over-split|helper|decomposition)\b", re.IGNORECASE)


def test_idiom_notes_follow_template_and_avoid_scoring_terms() -> None:
    notes = {path.stem: path for path in IDIOM_DIR.glob("*.md")}

    assert set(notes) == LANGUAGES
    for note_path in notes.values():
        content = note_path.read_text(encoding="utf-8")
        assert all(heading in content for heading in HEADINGS)
        assert not PROHIBITED.search(content)
        assert all(
            content.index(heading) < content.index(next_heading)
            for heading, next_heading in pairwise(HEADINGS)
        )


def test_idiom_hashes_match_note_contents() -> None:
    expected = {
        f"{language}.md": hashlib.sha256(
            (IDIOM_DIR / f"{language}.md").read_bytes()
        ).hexdigest()
        for language in LANGUAGES
    }
    actual = {}
    for line in (IDIOM_DIR / "hashes.txt").read_text(encoding="utf-8").splitlines():
        digest, filename = line.split(maxsplit=1)
        assert filename not in actual
        actual[filename] = digest

    assert actual == expected
