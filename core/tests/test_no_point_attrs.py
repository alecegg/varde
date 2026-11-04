import ast
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# tree-sitter 0.26.0 Point.row/column borrowed-reference bug
# (tree-sitter/py-tree-sitter#472, fixed by upstream PR #466). These source
# attributes are unrelated to tree-sitter Points.
ALLOWLIST = {
    "core/src/varde_core/yamlio.py": {
        "mark.column",
        "context_mark.column",
    },
    "learn/src/varde_learn/docs/flow/scan.py": {"self.row"},
    "code/src/varde_code/rules/pattern.py": {
        "rng.start.column",
        "rng.end.column",
    },
    # This fixture's row is a dict, not a tree-sitter Point.
    "runner/tests/test_takeover.py": {"self.row"},
}


def test_python_sources_do_not_access_tree_sitter_point_row_or_column() -> None:
    tracked_python_files = subprocess.run(
        ["git", "ls-files", "*.py"],  # noqa: S607 - Git is resolved from PATH to inspect this checkout.
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    sources = {
        path: (REPO_ROOT / path).read_text(encoding="utf-8")
        for path in tracked_python_files
        if not {".venv", ".git", "node_modules"}.intersection(Path(path).parts)
    }
    violations = point_attribute_violations(sources)

    assert not violations, "tree-sitter Point attribute access found:\n" + "\n".join(
        violations
    )


def point_attribute_violations(sources: dict[str, str]) -> list[str]:
    violations = []
    for relative_path, source in sources.items():
        if Path(relative_path).parts[:4] == (
            "code",
            "bench",
            "quality-corpus",
            "items",
        ):
            continue
        allowed = ALLOWLIST.get(relative_path, set())
        tree = ast.parse(source, filename=relative_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or node.attr not in {
                "row",
                "column",
            }:
                continue
            expression = ast.unparse(node)
            if expression not in allowed:
                violations.append(f"{relative_path}:{node.lineno}: {expression}")

    return violations


def test_point_attribute_violations_flags_real_code_paths() -> None:
    assert point_attribute_violations({"code/example.py": "value.row\n"}) == [
        "code/example.py:1: value.row"
    ]


def test_point_attribute_violations_skips_quality_corpus_items() -> None:
    assert (
        point_attribute_violations(
            {"code/bench/quality-corpus/items/example.py": "value.column\n"}
        )
        == []
    )
