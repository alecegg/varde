import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def test_serve_imports_no_cli_module_or_runner_or_app() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [
                f"{path.name}: {name}"
                for name in names
                if name.split(".")[0] in {"varde", "varde_runner"}
                or "cli" in name.split(".")
                or name.endswith("_cli")
            ]
    assert offenders == []
