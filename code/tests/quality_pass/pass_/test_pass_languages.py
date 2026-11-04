"""The pass runs over all seven release languages and resolves real imports."""

from __future__ import annotations

from pass_support import (
    build_index,
    facts_by_path,
    measures_by_path,
    prepare_env,
    write_repo,
)
from varde_code.quality_pass.pass_ import run_quality_pass

FILES = {
    "src/a.py": "import src.b\n\n\ndef alpha():\n    return src.b.beta()\n",
    "src/b.py": "def beta():\n    return 1\n",
    "src/c.ts": (
        'import { epsilon } from "./e";\n'
        "export function gamma() { return epsilon(); }\n"
    ),
    "src/d.js": "export function delta() { return 4; }\n",
    "src/e.tsx": "export function epsilon() { return 5; }\n",
    "src/F.java": "public class F { static int f() { return 6; } }\n",
    "src/g.go": "package g\n\nfunc G() int { return 7 }\n",
    "src/h.rs": "pub fn h() -> i32 { 8 }\n",
    "src/I.cs": "public class I { public static int J() { return 9; } }\n",
    "src/k.cpp": "int k() { return 10; }\n",
}
LANGUAGES = {
    "python",
    "typescript",
    "javascript",
    "tsx",
    "java",
    "go",
    "rust",
    "csharp",
    "cpp",
}


def test_every_release_language_produces_facts_and_measures(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, FILES)
    build_index(root)

    summary = run_quality_pass(root, workers=2)

    assert summary.file_count == len(FILES)
    facts = facts_by_path(root)
    assert {record["language"] for record in facts.values()} == LANGUAGES
    for path, record in facts.items():
        assert record["contract"] == "facts-2"
        assert record["functions"], path
    assert facts["src/c.ts"]["imports"] == [
        {
            "line": 1,
            "module": "./e",
            "text": 'import { epsilon } from "./e";',
        }
    ]

    measures = measures_by_path(root)
    gamma = measures["src/c.ts"]["functions"]["src/c.ts::gamma#1"]
    assert gamma["depth"] == 1
    assert gamma["distinct_callees"] == 1
    assert gamma["tree_size"] == 1
    assert measures["src/c.ts"]["import_fan_out"] == 1
