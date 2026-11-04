"""Exact stdout/stderr storage in private versioned files."""

from __future__ import annotations

import os
import secrets
import struct
import time
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"TOZRAW01"
HEADER = struct.Struct("<8sQQQ")


@dataclass(frozen=True)
class RawHandle:
    value: str

    @classmethod
    def parse(cls, value: str) -> RawHandle:
        if (
            len(value) != 33
            or value[0] != "r"
            or any(c not in "0123456789abcdef" for c in value[1:])
        ):
            raise ValueError("invalid exact output handle")
        return cls(value)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class RawOutputBytes:
    stdout: bytes
    stderr: bytes


class RawStore:
    def __init__(
        self,
        directory: str | Path,
        *,
        enabled: bool = False,
        max_bytes: int = 1_000_000,
        ttl_secs: int = 86400,
    ):
        self.directory = Path(directory)
        self.enabled = enabled
        self.max_bytes = max_bytes
        self.ttl_secs = ttl_secs

    def store(self, source_key: str, stdout: bytes, stderr: bytes = b"") -> RawHandle:
        if not self.enabled:
            raise ValueError("exact output storage is disabled")
        if len(stdout) + len(stderr) > self.max_bytes:
            raise ValueError("exact output exceeds configured limit")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        handle = RawHandle("r" + secrets.token_hex(16))
        path = self.directory / handle.value
        record = (
            HEADER.pack(
                MAGIC, int(time.time()) + self.ttl_secs, len(stdout), len(stderr)
            )
            + stdout
            + stderr
        )
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(record)
        return handle

    def get(self, handle: RawHandle) -> RawOutputBytes:
        path = self.directory / handle.value
        data = path.read_bytes()
        if len(data) < HEADER.size:
            raise ValueError("exact output record is corrupt")
        magic, expiry, out_size, err_size = HEADER.unpack(data[: HEADER.size])
        if magic != MAGIC or len(data) != HEADER.size + out_size + err_size:
            raise ValueError("exact output record is corrupt")
        if int(time.time()) >= expiry:
            path.unlink(missing_ok=True)
            raise ValueError("exact output has expired")
        offset = HEADER.size
        return RawOutputBytes(
            data[offset : offset + out_size], data[offset + out_size :]
        )

    def prune(self) -> int:
        removed = 0
        for path in self.directory.iterdir() if self.directory.exists() else ():
            try:
                data = path.read_bytes()[: HEADER.size]
                _, expiry, _, _ = HEADER.unpack(data)
            except OSError, struct.error:
                continue
            if int(time.time()) >= expiry:
                path.unlink(missing_ok=True)
                removed += 1
        return removed
