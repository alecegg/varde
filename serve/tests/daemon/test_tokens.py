"""Token creation is exclusive: concurrent first starts agree on one value."""

import stat
import threading
from pathlib import Path

from varde_serve.daemon.tokens import ensure_tokens, read_mcp_token


def test_concurrent_first_creation_yields_one_value(tmp_path: Path) -> None:
    results = []
    gate = threading.Barrier(8)

    def create() -> None:
        gate.wait()
        results.append(ensure_tokens(tmp_path))

    threads = [threading.Thread(target=create) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 8
    assert len(set(results)) == 1
    assert read_mcp_token(tmp_path) == results[0].mcp
    for name in ("token", "mcp-token"):
        mode = stat.S_IMODE((tmp_path / "serve" / name).stat().st_mode)
        assert mode == 0o600
    assert [
        p.name for p in (tmp_path / "serve").iterdir() if p.name.startswith(".")
    ] == []
