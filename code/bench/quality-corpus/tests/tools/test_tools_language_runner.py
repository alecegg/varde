from pathlib import Path

import pytest
from behaviour_runner import available_commands, run_item, unavailable_reason

VERSIONS = ("sensible", "monolith", "tiny", "padded", "sizematched", "namematched")


def write_item(root: Path, suffix: str) -> Path:
    item = root / "language-pair"
    item.mkdir()
    sources = {
        ".py": "def answer(): return 42\n",
        ".ts": "export function answer(): number { return 42; }\n",
        ".go": "package corpus\nfunc Answer() int { return 42 }\n",
        ".rs": "pub fn answer() -> i32 { 42 }\n",
        ".cpp": "int answer() { return 42; }\n",
        ".java": "class solution { static int answer() { return 42; } }\n",
        ".cs": "public static class solution { public static int Answer() => 42; }\n",
    }
    tests = {
        ".py": "import solution\nassert solution.answer() == 42\n",
        ".ts": (
            "import { answer } from './solution.ts';\n"
            "if (answer() !== 42) throw new Error('mismatch');\n"
        ),
        ".go": (
            'package corpus\nimport "testing"\n'
            "func TestBehaviour(t *testing.T) { if Answer() != 42 "
            '{ t.Fatal("mismatch") } }\n'
        ),
        ".rs": (
            "use corpus::answer;\n#[test]\n"
            "fn behaviour() { assert_eq!(answer(), 42); }\n"
        ),
        ".cpp": (
            '#include "solution.cpp"\nint main() { return answer() == 42 ? 0 : 1; }\n'
        ),
        ".java": (
            "class behaviour_test { public static void main(String[] args) { "
            "if (solution.answer() != 42) throw new RuntimeException(); } }\n"
        ),
        ".cs": "if (solution.Answer() != 42) throw new System.Exception();\n",
    }
    for version in VERSIONS:
        (item / f"{version}{suffix}").write_text(sources[suffix])
    (item / f"behaviour_test{suffix}").write_text(tests[suffix])
    return item


@pytest.mark.parametrize(
    "language,suffix",
    [
        ("python", ".py"),
        ("node/typescript", ".ts"),
        ("go", ".go"),
        ("cargo/rust", ".rs"),
        ("g++/clang++", ".cpp"),
        ("java/javac", ".java"),
        ("dotnet", ".cs"),
    ],
)
def test_each_installed_language_runs_shared_test_on_six_versions(
    tmp_path: Path, language: str, suffix: str
) -> None:
    if available_commands(suffix) is None:
        pytest.skip(f"{language}: {unavailable_reason(suffix)}")
    assert run_item(write_item(tmp_path, suffix)) == []
