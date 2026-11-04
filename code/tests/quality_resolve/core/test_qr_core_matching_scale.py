import time

from varde_code.quality_resolve.core import _matching, _target_details


def test_matching_scans_only_paths_declaring_the_key():
    scope = {f"src/File{index}.cs" for index in range(20_000)}
    records = {
        "src/File7.cs": {"run": [{"id": "a", "params": 1}]},
        "src/File3.cs": {"run": [{"id": "b", "params": 1}]},
        "src/File9.cs": {"other": [{"id": "c", "params": 1}]},
    }
    started = time.perf_counter()
    found = _matching(scope, records, "run", 1)
    for _ in range(299):
        _matching(scope, records, "run", 1)
    assert [(path, record["id"]) for path, record in found] == [
        ("src/File3.cs", "b"),
        ("src/File7.cs", "a"),
    ]
    assert time.perf_counter() - started < 10


def test_matching_falls_back_to_lenient_optional_parameters():
    records = {"a.py": {"run": [{"id": "x", "params": 3}]}}
    assert _matching({"a.py"}, records, "run", 2) == [
        ("a.py", {"id": "x", "params": 3})
    ]
    assert _matching({"a.py"}, records, "run", 5) == []


def test_target_details_cache_matches_uncached():
    facts = {"a.py": {"functions": [{"id": "1", "name": "f", "owner": "O"}]}}
    cache = {}
    assert _target_details({"a.py"}, facts, "O", cache) == _target_details(
        {"a.py"}, facts, "O"
    )
    assert ("a.py", "O") in cache
