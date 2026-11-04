"""Pure ranking helpers for context_pack lexical and structural results."""

from __future__ import annotations

import re


def fuse_rankings(
    structural: list[int],
    lexical_entities: list[tuple[int, float]],
    entity_files: dict[int, int],
    k: int = 60,
) -> dict[int, float]:
    """Fuse file rankings with reciprocal rank fusion, aggregating lexical hits by
    file.
    """
    scores: dict[int, float] = {}
    lexical = _lexical_files(lexical_entities, entity_files, k)
    for ranking in (structural, lexical):
        for rank, file_id in enumerate(ranking, start=1):
            scores[file_id] = scores.get(file_id, 0.0) + 1.0 / (k + rank)
    return scores


def rerank_files(
    scores: dict[int, float],
    paths: dict[int, str],
    query: str,
    entity_names: dict[int, set[str]],
) -> list[int]:
    """Apply path noise penalties and a small exact entity-name token boost."""
    tokens = {token.lower() for token in re.findall(r"\w+", query)}

    def rank(file_id: int) -> tuple[float, str]:
        path = paths[file_id].lower().replace("\\", "/")
        penalty = 0.03 if _is_test_path(path) else 0.0
        if any(
            part in path.split("/")
            for part in ("vendor", "vendors", "third_party", "third-party")
        ):
            penalty += 0.05
        if any(
            marker in path for marker in ("generated", ".g.cs", ".pb.", "_generated.")
        ):
            penalty += 0.05
        names = entity_names.get(file_id, set())
        boost = 0.02 if any(name.lower() in tokens for name in names) else 0.0
        return scores[file_id] + boost - penalty, paths[file_id]

    return sorted(scores, key=lambda file_id: (-rank(file_id)[0], rank(file_id)[1]))


def _lexical_files(
    entities: list[tuple[int, float]], entity_files: dict[int, int], k: int
) -> list[int]:
    scores: dict[int, float] = {}
    for rank, (entity_id, _score) in enumerate(entities, start=1):
        file_id = entity_files.get(entity_id)
        if file_id is not None:
            scores[file_id] = scores.get(file_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda file_id: (-scores[file_id], file_id))


def _is_test_path(path: str) -> bool:
    return any(
        part in {"test", "tests", "__tests__"} or part.startswith("test_")
        for part in path.split("/")
    )
