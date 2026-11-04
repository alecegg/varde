from __future__ import annotations

import json

from varde_code.query.context_budget import fit_sections
from varde_code.query.output import render


def _pack(files: int, per_file: int = 20) -> dict:
    paths = [f"src/pkg/module_{i}.py" for i in range(files)]
    return {
        "files": [
            {"path": p, "relevance": "seed" if i < 3 else "neighbor"}
            for i, p in enumerate(paths)
        ],
        "symbols": [
            {
                "name": f"symbol_{i}_{j}",
                "filePath": p,
                "kind": "function",
                "span": {"start_line": j, "end_line": j + 1},
            }
            for i, p in enumerate(paths)
            for j in range(per_file)
        ],
        "tests": [
            {"path": f"tests/test_{i}_{j}.py", "coversFile": p}
            for i, p in enumerate(paths)
            for j in range(per_file)
        ],
        "readingOrder": list(paths),
    }


def _render(data: dict, **options) -> dict:
    return render(
        data, {"repoRoot": "/r", "mode": "context_pack", "query": "x", **options}
    )


def _size(result: dict) -> int:
    return len(json.dumps(result, separators=(",", ":")).encode())


def test_default_call_stays_under_cap_and_flags_truncation():
    result = _render(_pack(300))
    assert _size(result) <= 4000 * 4
    assert result["meta"]["truncated"] is True
    pagination = result["meta"]["pagination"]
    assert {"files", "symbols", "tests"} <= set(pagination)
    data = result["data"]
    assert pagination["symbols"]["shown"] == len(data["symbols"])
    assert pagination["symbols"]["total"] == len(data["files"]) * 20
    assert set(data["readingOrder"]) == {item["path"] for item in data["files"]}


def test_budget_drops_lowest_ranked_items():
    data = _pack(300)
    result = _render(data)["data"]
    assert result["files"] == data["files"][: len(result["files"])]
    assert result["symbols"] == data["symbols"][: len(result["symbols"])]


def test_max_tokens_estimate_is_honored():
    small = _size(_render(_pack(300), maxTokensEstimate=1000))
    assert small <= 4000


def test_results_limit_bounds_every_list():
    result = _render(_pack(300), resultsLimit=5)
    data = result["data"]
    assert len(data["files"]) == 5
    assert len(data["symbols"]) <= 5
    assert len(data["tests"]) <= 5
    assert len(data["readingOrder"]) <= 5
    assert result["meta"]["truncated"] is True


def test_full_results_bypasses_caps():
    data = _pack(300)
    result = _render(data, fullResults=True)
    assert len(result["data"]["symbols"]) == 300 * 20
    assert len(result["data"]["tests"]) == 300 * 20
    assert result["meta"]["truncated"] is False
    assert "pagination" not in result["meta"]


def test_small_result_is_not_truncated():
    result = _render(_pack(3, per_file=2))
    assert result["meta"]["truncated"] is False
    assert "pagination" not in result["meta"]
    assert len(result["data"]["symbols"]) == 6


def test_invalid_max_tokens_estimate_is_rejected():
    result = _render(_pack(3), maxTokensEstimate=0)
    assert result["ok"] is False


def test_fit_sections_trims_the_largest_section_tail_first():
    kept = fit_sections({"a": [10] * 10, "b": [1] * 10}, budget=60)
    assert kept == {"a": 5, "b": 10}
    assert fit_sections({"a": [5]}, budget=100) == {"a": 1}
    assert fit_sections({"a": [5, 5]}, budget=0) == {"a": 0}


def test_tiny_budget_keeps_one_file_and_advances():
    for budget in (1, 300):
        result = _render(_pack(5), maxTokensEstimate=budget)
        files = result["meta"]["pagination"]["files"]
        assert len(result["data"]["files"]) == 1
        assert files["next_offset"] == 1


def test_tiny_budget_pages_to_the_end():
    seen = []
    offset = 0
    for _ in range(10):
        result = _render(_pack(5), maxTokensEstimate=1, resultsOffset=offset)
        seen += [item["path"] for item in result["data"]["files"]]
        pagination = result["meta"].get("pagination", {}).get("files")
        if not pagination or pagination["next_offset"] is None:
            break
        offset = pagination["next_offset"]
    assert seen == [f"src/pkg/module_{i}.py" for i in range(5)]


def test_symbols_follow_the_offset_file_page_with_page_totals():
    result = _render(_pack(10), resultsOffset=3, resultsLimit=3)
    data = result["data"]
    assert [f["path"] for f in data["files"]] == [
        f"src/pkg/module_{i}.py" for i in (3, 4, 5)
    ]
    assert {s["filePath"] for s in data["symbols"]} == {"src/pkg/module_3.py"}
    assert {t["coversFile"] for t in data["tests"]} <= {
        f"src/pkg/module_{i}.py" for i in (3, 4, 5)
    }
    symbols = result["meta"]["pagination"]["symbols"]
    assert symbols["total"] == 3 * 20
    assert result["meta"]["pagination"]["files"]["next_offset"] == 6


def test_offset_past_the_end_is_empty():
    result = _render(_pack(3), resultsOffset=10)
    assert result["data"]["files"] == []
    assert result["data"]["symbols"] == []


def test_non_ascii_content_stays_under_cap_in_utf8_bytes():
    data = _pack(300)
    for item in data["symbols"]:
        item["name"] = "\u00e9\u4e2d" * 5
    result = _render(data)
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= 4000 * 4


def test_full_results_with_occurrences_returns_everything():
    result = _render(_pack(300), fullResults=True, includeOccurrences=True)
    assert len(result["data"]["files"]) == 300
    assert result["meta"]["truncated"] is False
