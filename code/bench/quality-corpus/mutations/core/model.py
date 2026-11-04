"""Mutation records and reproducible seed derivation."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class MutationMetadata:
    operator: str
    expected_direction: str
    seed: int
    pair_group_id: str
    status: str = "mutated"
    skip_reason: str | None = None


@dataclass(frozen=True)
class Mutation:
    source: str
    metadata: MutationMetadata

    def to_dict(self) -> dict[str, object]:
        """Return an artifact-ready record that keeps each mutant tied to its base."""
        return {"source": self.source, "metadata": vars(self.metadata)}

    @property
    def skipped(self) -> bool:
        return self.metadata.status == "skipped"


def stable_seed(operator: str, source: str, seed: int | None = None) -> int:
    """Derive a stable seed from operator and source, independent of Python hash."""
    digest = hashlib.blake2b(f"{operator}\0{source}".encode(), digest_size=8).digest()
    return (int.from_bytes(digest, "big") if seed is None else seed) % (2**63)


def make_mutation(
    source: str,
    operator: str,
    expected_direction: str,
    pair_group_id: str,
    seed: int | None = None,
    skip_reason: str | None = None,
) -> Mutation:
    if not pair_group_id.strip():
        raise ValueError("pair_group_id must be non-empty")
    resolved_seed = stable_seed(operator, source, seed)
    return Mutation(
        source,
        MutationMetadata(
            operator,
            expected_direction,
            resolved_seed,
            pair_group_id,
            "skipped" if skip_reason else "mutated",
            skip_reason,
        ),
    )


def random_for(operator: str, source: str, seed: int | None) -> random.Random:
    return random.Random(stable_seed(operator, source, seed))  # noqa: S311 - Mutation generation needs reproducible randomness only.
