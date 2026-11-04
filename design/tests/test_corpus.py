"""Corpus manifest, planted-defect fixture pairs and the corpus tool."""

import hashlib
import importlib.util
import json
import re
from pathlib import Path

from varde_design.registry import rule_ids

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parent
CORPUS_TOOL = PACKAGE / "corpus" / "corpus.py"
MANIFEST = json.loads((PACKAGE / "corpus" / "manifest.json").read_text())
FIXTURES = REPO / MANIFEST["synthetic"]["root"]
PERMISSIVE = {"MIT", "BSD-3-Clause", "BSD-2-Clause", "Apache-2.0", "ISC"}
HEX64 = re.compile(r"[0-9a-f]{64}")
HEX40 = re.compile(r"[0-9a-f]{40}")


def _load_tool():
    spec = importlib.util.spec_from_file_location("corpus_tool", CORPUS_TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def test_third_party_set_has_about_ten_distinct_systems() -> None:
    pages = MANIFEST["third_party"]
    assert 10 <= len(pages) <= 12
    assert len({p["design_system"] for p in pages}) == len(pages)
    assert len({p["id"] for p in pages}) == len(pages)


def test_each_third_party_page_records_source_licence_and_hashes() -> None:
    for page in MANIFEST["third_party"]:
        assert page["url"].startswith("https://github.com/"), page["id"]
        assert HEX40.fullmatch(page["commit"]), page["id"]
        assert page["commit"] in page["url"], page["id"]
        assert page["licence"] in PERMISSIVE, page["id"]
        assert page["licence_url"].startswith("https://github.com/"), page["id"]
        assert page["vendored"] is False, page["id"]
        assert set(page["sha256"]) == set(tool.source_paths(page)), page["id"]
        assert all(HEX64.fullmatch(h) for h in page["sha256"].values()), page["id"]


def test_no_third_party_file_is_committed_in_the_module() -> None:
    pinned = {h for page in MANIFEST["third_party"] for h in page["sha256"].values()}
    committed = {
        hashlib.sha256(p.read_bytes()).hexdigest()
        for p in PACKAGE.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and ".venv" not in p.parts
    }
    assert pinned & committed == set()


def test_varde_pages_are_pinned_not_vendored() -> None:
    pages = MANIFEST["varde"]["pages"]
    assert len(pages) >= 58
    assert all(p.endswith(".html") and HEX64.fullmatch(h) for p, h in pages.items())
    assert MANIFEST["varde"]["vendored"] is False


def test_every_registry_rule_has_a_defect_and_clean_pair() -> None:
    pairs = MANIFEST["synthetic"]["rule_pairs"]
    assert [p["rule"] for p in pairs] == list(rule_ids())
    assert len(pairs) == 18


def test_fixture_pairs_exist_differ_and_carry_markers() -> None:
    for pair in MANIFEST["synthetic"]["rule_pairs"]:
        rule = pair["rule"]
        defect = (FIXTURES / pair["defect"]).read_text()
        clean = (FIXTURES / pair["clean"]).read_text()
        assert defect != clean, rule
        assert f"planted defect: {rule} " in defect, rule
        assert f"clean twin: {rule} " in clean, rule
        assert "planted defect" not in clean, rule


def test_synthetic_pages_exist_and_one_has_no_design_system() -> None:
    synthetic = MANIFEST["synthetic"]
    assert len(synthetic["pages"]) == 3
    for page in synthetic["pages"]:
        assert (FIXTURES / page).is_file(), page
    bare = (FIXTURES / synthetic["no_system_page"]).read_text().lower()
    assert all(token not in bare for token in ("<style", "style=", "stylesheet", "--"))


def test_raw_url_pins_commit() -> None:
    url = tool.raw_url("a/b", "c" * 40, "x/y.html")
    assert url == f"https://raw.githubusercontent.com/a/b/{'c' * 40}/x/y.html"


def test_pin_and_fetch_detect_changed_content(tmp_path: Path) -> None:
    page = {
        "id": "p",
        "repo": "a/b",
        "commit": "c" * 40,
        "path": "i.html",
        "companions": ["s.css"],
    }
    tool.pin_page(page, lambda url: url.encode())
    assert set(page["sha256"]) == {"i.html", "s.css"}
    assert tool.fetch_page(page, tmp_path, lambda url: url.encode()) == []
    assert (tmp_path / "p" / "i.html").is_file()
    assert tool.fetch_page(page, tmp_path, lambda url: b"changed") == [
        "i.html",
        "s.css",
    ]
