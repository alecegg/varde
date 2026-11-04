"""Deterministic MinHash signatures for function body clone detection."""

from __future__ import annotations

import re
from functools import lru_cache

SHINGLE_SIZE = 5
NUM_HASHES = 16
BANDS = 4
ROWS = NUM_HASHES // BANDS
FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
MASK = 0xFFFFFFFFFFFFFFFF
SEED_MIX = 0x9E3779B97F4A7C15
SEEDS = tuple(FNV_OFFSET ^ (((i + 1) * SEED_MIX) & MASK) for i in range(NUM_HASHES))
_TOKEN_RE = re.compile(r"[^\W_]+")


def _update(value: int, byte: int) -> int:
    return ((value ^ byte) * FNV_PRIME) & MASK


def body_minhash(text: str) -> list[int] | None:
    tokens = [part.lower() for part in _TOKEN_RE.findall(text)]
    if len(tokens) < SHINGLE_SIZE:
        return None
    minima = [MASK] * NUM_HASHES
    hash_shingle = _hash_shingle
    shingle_size = SHINGLE_SIZE
    for start in range(len(tokens) - SHINGLE_SIZE + 1):
        shingle = " ".join(tokens[start : start + shingle_size]).encode("utf-8")
        for index, value in enumerate(hash_shingle(shingle)):
            minima[index] = min(minima[index], value)
    return [
        _band_hash(minima[i : i + ROWS], SEEDS[band])
        for band, i in enumerate(range(0, NUM_HASHES, ROWS))
    ]


@lru_cache(maxsize=65536)
def _hash_shingle(shingle: bytes) -> tuple[int, ...]:
    seeds = SEEDS
    prime = FNV_PRIME
    mask = MASK
    hashes = []
    for seed in seeds:
        value = seed
        for byte in shingle:
            value = ((value ^ byte) * prime) & mask
        hashes.append(value)
    return tuple(hashes)


def _band_hash(rows: list[int], seed: int) -> int:
    value = seed
    for row in rows:
        for byte in row.to_bytes(8, "little"):
            value = _update(value, byte)
    return value
