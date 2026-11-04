from collections import Counter

import pytest
from audit.records import validate_record
from audit.sampling import CALL_CLASSES, sample_sets


def _sites() -> list[dict[str, object]]:
    return [
        {
            "repo": f"repo-{repo}",
            "language": "python",
            "file": f"src/{repo}.py",
            "line": line + 1,
            "call_class": call_class,
            "ground_truth": "unknown"
            if call_class in {"dynamic", "higher_order"}
            else "target",
            "measured_edge": "target"
            if call_class not in {"dynamic", "higher_order"}
            else None,
            "measured_status": "resolved"
            if call_class not in {"dynamic", "higher_order"}
            else "opaque",
            "truth_source": "hand_checked",
            "function_id": f"caller-{repo}",
            "module": f"module-{repo}",
            "ground_truth_module": f"module-{repo}",
            "measured_module": f"module-{repo}",
        }
        for repo in range(12)
        for call_class in CALL_CLASSES
        for line in range(6)
    ]


def test_sampling_is_seeded_balanced_and_repo_disjoint() -> None:
    sites = _sites()
    first = sample_sets(sites, seed=17, n_per_language=12)
    assert first == sample_sets(sites, seed=17, n_per_language=12)
    assert first != sample_sets(sites, seed=18, n_per_language=12)
    dev, test = first["python"]["dev"], first["python"]["test"]
    expected = Counter(dict.fromkeys(CALL_CLASSES, 2))
    assert Counter(row["call_class"] for row in dev) == expected
    assert Counter(row["call_class"] for row in test) == expected
    assert {row["repo"] for row in dev}.isdisjoint({row["repo"] for row in test})
    for record in dev + test:
        validate_record(record)


def test_sampling_rejects_insufficient_class_capacity() -> None:
    sites = [
        site
        for site in _sites()
        if site["repo"] in {"repo-0", "repo-1"} and site["line"] == 1
    ]
    with pytest.raises(ValueError, match="needs 2"):
        sample_sets(sites, seed=1, n_per_language=12)
