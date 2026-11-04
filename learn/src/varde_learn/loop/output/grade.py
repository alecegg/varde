"""Grade deterministic and judge results for an eval run."""

from __future__ import annotations

import json
from typing import Any


def strip_code_fences(text: str) -> str:
    value = text.strip()
    if value.startswith("```json"):
        value = value[7:]
    elif value.startswith("```"):
        value = value[3:]
    value = value.removesuffix("```")
    return value.strip()


def value_to_grade_result(item: Any) -> dict[str, str] | None:
    if (
        not isinstance(item, dict)
        or not isinstance(item.get("assertion"), str)
        or not isinstance(item.get("verdict"), str)
    ):
        return None
    evidence = item.get("evidence", "")
    return {
        "assertion": item["assertion"],
        "verdict": item["verdict"],
        "evidence": evidence if isinstance(evidence, str) else "",
    }


def parse_judge_results(text: str) -> list[dict[str, str]]:
    try:
        value = json.loads(strip_code_fences(text))
    except ValueError, TypeError:
        return []
    if not isinstance(value, dict) or not isinstance(value.get("results"), list):
        return []
    return [
        result
        for item in value["results"]
        if (result := value_to_grade_result(item)) is not None
    ]


def merge_results(
    declared: list[str],
    deterministic: list[dict[str, Any]],
    judged: list[dict[str, str]],
) -> list[dict[str, str]]:
    covered = {
        item["assertion"]: item
        for item in (*deterministic, *judged)
        if isinstance(item.get("assertion"), str)
    }
    return [
        covered.get(
            assertion,
            {
                "assertion": assertion,
                "verdict": "FAIL",
                "evidence": "No grading result returned",
            },
        )
        for assertion in declared
    ]


def grade_results(
    declared: list[str],
    deterministic: list[dict[str, Any]],
    judged: list[dict[str, str]],
    run_outcome: str = "completed",
) -> dict[str, Any]:
    """Combine assertion verdicts and summarize pass count."""
    if run_outcome != "completed":
        evidence = "Evaluated run failed; assertions cannot pass"
        results = [
            {"assertion": assertion, "verdict": "FAIL", "evidence": evidence}
            for assertion in declared
        ]
    else:
        results = merge_results(declared, deterministic, judged)
    return {
        "total": len(results),
        "passed": sum(item["verdict"] == "PASS" for item in results),
        "results": results,
        "run_outcome": run_outcome,
    }
