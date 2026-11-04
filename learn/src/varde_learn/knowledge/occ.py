"""Optimistic concurrency versioning for concept file bytes."""

from hashlib import sha256


def version(data: bytes) -> str:
    """Return the first 16 hexadecimal characters of the SHA-256 digest."""
    return sha256(data).hexdigest()[:16]
