"""Deterministic cache keys and canonical serialization for the quality pass.

Every key hashes the bytes the pass read and parsed (never the fast index's
FNV hash), and every serialized fingerprint sorts its inputs first.
"""

from __future__ import annotations

import hashlib
import json

DIGEST_SIZE = 32
H_HOPS = 6
MICRO = 1_000_000
MEASURE_VERSION = "quality-measures-1"


def canonical_json(value: object) -> str:
    """Serialize ``value`` with sorted keys and no incidental whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def blake2b_digest(value: bytes | str, *, size: int = DIGEST_SIZE) -> str:
    """Return ``blake2b-<hex>`` for bytes or UTF-8 text."""
    data = value.encode("utf-8") if isinstance(value, str) else value
    return f"blake2b-{hashlib.blake2b(data, digest_size=size).hexdigest()}"


def content_digest(raw: bytes) -> str:
    """Return the content hash of the bytes the pass read and parsed."""
    return blake2b_digest(raw)


def language_profile_version(language: str) -> str:
    """Return the language-profile version of the per-language fact hooks."""
    return f"quality-profile-{language}-2"


def facts_key(content_hash: str, language: str, extractor_version: str) -> str:
    """Return the L1 key: parsed bytes plus extractor and profile versions."""
    return canonical_json(
        [content_hash, extractor_version, language_profile_version(language)]
    )


def edges_key(facts_key_value: str, digest: str, resolver_version: str) -> str:
    """Return the L2 key: the L1 key, the resolver version and its digest."""
    return blake2b_digest(canonical_json([facts_key_value, resolver_version, digest]))


def measure_key(
    *,
    module: str,
    edge_key_value: str,
    fingerprints: list[tuple[str, str]],
    module_signature: str,
    tfrag: int,
    hop_limit: int = H_HOPS,
) -> str:
    """Return the L3 key over forward fingerprints and the module's state.

    The per-hop Merkle fingerprints cover the forward closure; the file's L2
    key covers a function-less file's own edges and coverage; the module
    signature covers reverse measures (callers, fragments, dominators) and the
    module's expansion cap, which the forward fingerprint does not.
    """
    return blake2b_digest(
        canonical_json(
            [
                MEASURE_VERSION,
                hop_limit,
                tfrag,
                module,
                edge_key_value,
                sorted(fingerprints),
                module_signature,
            ]
        )
    )
