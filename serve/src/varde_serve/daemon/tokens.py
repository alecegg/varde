"""Owner-only token files in the serve state directory."""

from __future__ import annotations

import contextlib
import os
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path

MCP_FILE = "mcp-token"
HUMAN_FILE = "token"


@dataclass(frozen=True)
class Tokens:
    human: str
    mcp: str


class TokenMissing(RuntimeError):
    """A token file the caller may only read does not exist."""


def state_dir(config_dir: Path) -> Path:
    path = config_dir / "serve"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def _create_exclusive(path: Path, value: str) -> bool:
    """Publish `value` at `path` complete and 0600, unless it already exists."""
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".token-")
    try:
        os.write(descriptor, value.encode())
        os.fchmod(descriptor, 0o600)
        os.close(descriptor)
        os.link(temporary, path)  # fails if `path` exists: first writer wins
    except FileExistsError:
        return False
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
    return True


def _ensure(path: Path) -> str:
    """Read the token, creating it if missing; concurrent creators agree."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        pass
    _create_exclusive(path, secrets.token_hex(32))
    return path.read_text(encoding="utf-8").strip()


def ensure_tokens(config_dir: Path) -> Tokens:
    """Read or create both tokens; for the daemon and the human CLI only."""
    directory = state_dir(config_dir)
    return Tokens(_ensure(directory / HUMAN_FILE), _ensure(directory / MCP_FILE))


def read_mcp_token(config_dir: Path) -> str:
    """Read only `mcp-token` (the agent side never touches the human token)."""
    path = config_dir / "serve" / MCP_FILE
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise TokenMissing(f"{path} does not exist; the daemon creates it") from None


def token_file_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777
