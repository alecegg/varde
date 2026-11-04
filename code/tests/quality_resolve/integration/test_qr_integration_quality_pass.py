"""Exercise deep call resolution through the cached quality pass."""

from __future__ import annotations

import json
import sqlite3

from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.build import build
from varde_code.index.incremental import refresh
from varde_code.quality_pass.pass_ import run_quality_pass
from varde_code.quality_pass.store import quality_store_path
from varde_code.query import modes

REPO = {
    "py/main.py": "def local():\n    return 1\n\ndef entry():\n    return local()\n",
    "py/helper.py": "def compute():\n    return 1\n",
    "ts/main.ts": (
        'import { compute } from "./helper";\n'
        "export function entry() { return compute(); }\n"
    ),
    "ts/helper.ts": "export function compute() { return 1; }\n",
    "java/A.java": "package java; class A { B run() { return new B(); } }\n",
    "java/B.java": "package java; class B {}\n",
    "other/idle.py": "def idle():\n    return 0\n",
}


def _prepare(root, monkeypatch):
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(root / "config"))
    monkeypatch.setattr(modes, "_INDEX_SERVICE", None)
    repo = root / "repo"
    repo.mkdir(parents=True)
    return repo


def _write_repo(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _cached_edges(root, path):
    with sqlite3.connect(quality_store_path(root)) as connection:
        row = connection.execute(
            "SELECT value FROM edges WHERE path=? ORDER BY rowid DESC LIMIT 1",
            (path,),
        ).fetchone()
    assert row is not None, path
    return json.loads(row[0])


def test_pass_cold_warm_and_per_file_invalidation_use_deep_edges(tmp_path, monkeypatch):
    root = _prepare(tmp_path, monkeypatch)
    _write_repo(root, REPO)
    build(root, CodeExtractionProvider())

    cold = run_quality_pass(root, workers=1)
    cold_edges = {path: _cached_edges(root, path) for path in REPO}
    assert cold.edges_recomputed == tuple(sorted(REPO))
    assert any(edge["pass"] == "imported" for edge in cold_edges["ts/main.ts"])  # noqa: S105 - Resolver pass labels are fixture values, not credentials.
    assert cold_edges["py/main.py"][0]["pass"] == "local"  # noqa: S105 - Resolver pass labels are fixture values, not credentials.

    warm = run_quality_pass(root, workers=1)
    assert warm.edges_recomputed == ()
    assert {path: _cached_edges(root, path) for path in REPO} == cold_edges

    (root / "ts/helper.ts").write_text(
        "export function calculate() { return 2; }\n", encoding="utf-8"
    )
    refresh(root, CodeExtractionProvider())
    edited = run_quality_pass(root, workers=1)

    assert edited.edges_recomputed == ("ts/helper.ts", "ts/main.ts")
    assert {
        path: _cached_edges(root, path) for path in REPO if path.startswith("py/")
    } == {path: cold_edges[path] for path in REPO if path.startswith("py/")}
    assert _cached_edges(root, "ts/main.ts")[0]["kind"] == "opaque"
