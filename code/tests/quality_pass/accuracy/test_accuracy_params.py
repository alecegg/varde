"""A18: parameter counts measured against hand-labelled fixture functions.

Labels in ``fixtures/accuracy/labels/params.json`` were counted by hand from
the declared parameter lists; the counting rule and the per-language set sizes
are recorded in ``fixtures/accuracy/README.md``. Fixtures keep at most one
function per owner and name so a label key is unambiguous.
"""

from __future__ import annotations

import pytest
from accuracy_audit import (
    fixture_facts,
    fixture_language,
    fixture_path,
    function_key,
    labels,
    record_rate,
)

PARAM_LABELS = labels("params.json")
PARAM_PATHS = sorted(PARAM_LABELS)
THRESHOLD = 0.99

# The fixed audit set has no remaining parameter-count misses.
# The corrected C++ owner key (Store.extra) has the same hand-counted arity,
# so the formerly stale fixtures.extra key no longer contributes a miss.
KNOWN_MISSES: tuple[tuple[str, str, int, int, str], ...] = ()


def _engine_params(relative_path: str) -> dict[str, int]:
    return {
        function_key(function): function["params"]
        for function in fixture_facts(relative_path)["functions"]
    }


def _count(relative_paths: list[str]) -> tuple[int, int]:
    exact = total = 0
    for relative_path in relative_paths:
        actual = _engine_params(relative_path)
        for key, expected in PARAM_LABELS[relative_path].items():
            total += 1
            exact += actual.get(key) == expected
    return exact, total


def _computed_misses() -> list[tuple[str, str, int, int]]:
    misses = []
    for relative_path in PARAM_PATHS:
        actual = _engine_params(relative_path)
        for key, expected in PARAM_LABELS[relative_path].items():
            if actual.get(key) != expected:
                misses.append((relative_path, key, expected, actual.get(key)))
    return misses


def _rate_lines() -> list[str]:
    languages = sorted({fixture_language(fixture_path(path)) for path in PARAM_PATHS})
    lines = []
    for language in languages:
        paths = [
            path
            for path in PARAM_PATHS
            if fixture_language(fixture_path(path)) == language
        ]
        exact, total = _count(paths)
        lines.append(f"{language}: {exact}/{total} exact ({exact / total:.2%})")
    exact, total = _count(PARAM_PATHS)
    lines.append(f"all: {exact}/{total} exact ({exact / total:.2%})")
    causes = {(path, key): cause for path, key, _hand, _engine, cause in KNOWN_MISSES}
    lines.extend(
        f"miss: {path} {key}: hand={expected} engine={actual} "
        f"({causes.get((path, key), 'unrecorded')})"
        for path, key, expected, actual in _computed_misses()
    )
    return lines


@pytest.mark.parametrize("relative_path", PARAM_PATHS)
def test_a18_labels_and_engine_cover_the_same_functions(relative_path):
    actual = {
        function_key(function) for function in fixture_facts(relative_path)["functions"]
    }

    assert actual == set(PARAM_LABELS[relative_path])


def test_a18_parameter_counts_are_exact_on_at_least_99_percent():
    lines = _rate_lines()
    record_rate("A18 parameter counts", *lines)
    print("A18 " + "\nA18 ".join(lines))
    exact, total = _count(PARAM_PATHS)

    assert exact / total >= THRESHOLD


def test_a18_parameter_count_misses_are_the_recorded_set():
    computed = _computed_misses()
    recorded = [miss[:4] for miss in KNOWN_MISSES]
    print(
        "A18 computed misses: "
        + "; ".join(
            f"{path} {key}: hand={expected} engine={actual}"
            for path, key, expected, actual in computed
        )
    )

    assert computed == recorded
