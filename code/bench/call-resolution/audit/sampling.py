"""Deterministic, repository-disjoint call-site sampling."""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable, Mapping

from audit.records import validate_record

CALL_CLASSES = (
    "same_file",
    "imported",
    "member",
    "constructor",
    "higher_order",
    "dynamic",
)


def sample_sets(
    sites: Iterable[Mapping[str, object]], seed: int, n_per_language: int = 300
) -> dict[str, dict[str, list[dict[str, object]]]]:
    """Return balanced dev/test samples whose repository sets do not overlap."""
    if n_per_language < len(CALL_CLASSES):
        raise ValueError("n_per_language must provide at least one site per call class")

    grouped: dict[str, dict[str, list[dict[str, object]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for site in sites:
        validate_record(dict(site))
        language = _required_text(site, "language")
        repo = _required_text(site, "repo")
        call_class = _required_text(site, "call_class")
        if call_class not in CALL_CLASSES:
            raise ValueError(f"unsupported call class: {call_class}")
        grouped[language][repo].append(dict(site))

    result: dict[str, dict[str, list[dict[str, object]]]] = {}
    for language in sorted(grouped):
        result[language] = _sample_language(
            grouped[language], seed, language, n_per_language
        )
    return result


def _sample_language(
    repos: Mapping[str, list[dict[str, object]]], seed: int, language: str, size: int
) -> dict[str, list[dict[str, object]]]:
    if len(repos) < 2:
        raise ValueError(
            f"{language} requires at least two repositories for disjoint sets"
        )
    order = sorted(repos)
    random.Random(f"{seed}:{language}").shuffle(order)  # noqa: S311 - Reproducible dataset partitioning is not cryptographic.
    midpoint = len(order) // 2
    partitions = {"dev": order[:midpoint], "test": order[midpoint:]}
    result: dict[str, list[dict[str, object]]] = {}
    quotas = _quotas(size)
    for split, repo_names in partitions.items():
        by_class: dict[str, list[dict[str, object]]] = defaultdict(list)
        for repo in repo_names:
            for site in repos[repo]:
                by_class[str(site["call_class"])].append(site)
        selected: list[dict[str, object]] = []
        rng = random.Random(f"{seed}:{language}:{split}")  # noqa: S311 - Reproducible sample selection is not cryptographic.
        for call_class in CALL_CLASSES:
            candidates = sorted(by_class[call_class], key=_site_key)
            if len(candidates) < quotas[call_class]:
                raise ValueError(
                    f"{language} {split} has {len(candidates)} {call_class} sites; "
                    f"needs {quotas[call_class]}"
                )
            rng.shuffle(candidates)
            selected.extend(candidates[: quotas[call_class]])
        result[split] = sorted(selected, key=_site_key)
    return result


def _quotas(size: int) -> dict[str, int]:
    base, remainder = divmod(size, len(CALL_CLASSES))
    return {
        call_class: base + (index < remainder)
        for index, call_class in enumerate(CALL_CLASSES)
    }


def _required_text(site: Mapping[str, object], field: str) -> str:
    value = site.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"site requires non-empty {field}")
    return value


def _site_key(site: Mapping[str, object]) -> tuple[str, str, int, str]:
    return (
        str(site["repo"]),
        str(site["file"]),
        int(site["line"]),
        str(site["call_class"]),
    )
