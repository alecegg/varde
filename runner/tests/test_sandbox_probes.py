from __future__ import annotations

import errno
import importlib.util
import os
import shutil
import tempfile
from pathlib import Path

import pytest


def _conftest_module():
    path = Path(__file__).with_name("conftest.py")
    spec = importlib.util.spec_from_file_location("runner_probe_conftest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raise(error: Exception) -> None:
    raise error


class _ProbeSkipped(Exception):
    pass


def _capture_skip(reason: str) -> None:
    raise _ProbeSkipped(reason)


def test_unix_probe_skips_only_permission_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes = _conftest_module()
    monkeypatch.setattr(probes.pytest, "skip", _capture_skip)
    with pytest.raises(_ProbeSkipped, match="AF_UNIX"):
        probes._run_probe(
            lambda: probes._probe_unix_bind(
                lambda path: _raise(
                    PermissionError(errno.EPERM, "Operation not permitted")
                )
            ),
            probes._is_unix_sandbox_denial,
            "AF_UNIX socket bind denied by sandbox",
        )
    with pytest.raises(OSError, match="address unavailable"):
        probes._run_probe(
            lambda: probes._probe_unix_bind(
                lambda path: _raise(OSError(errno.EADDRINUSE, "address unavailable"))
            ),
            probes._is_unix_sandbox_denial,
            "AF_UNIX socket bind denied by sandbox",
        )


def test_unix_probe_falls_back_when_tmp_directory_creation_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probes = _conftest_module()
    original_mkdtemp = tempfile.mkdtemp
    attempts: list[str | None] = []

    def sandboxed_mkdtemp(
        suffix: str | None = None, prefix: str | None = None, dir: str | None = None
    ) -> str:
        attempts.append(dir)
        if dir == "/tmp":  # noqa: S108 - Test exercises fallback from the conventional temp directory.
            raise PermissionError(errno.EPERM, "Operation not permitted", dir)
        return original_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)

    short_tmp = Path(original_mkdtemp(prefix="p", dir=tempfile.gettempdir()))
    monkeypatch.setenv("TMPDIR", str(short_tmp))
    monkeypatch.setattr(probes.tempfile, "mkdtemp", sandboxed_mkdtemp)
    bound_paths: list[str] = []

    probes._probe_unix_bind(bound_paths.append)

    try:
        assert attempts == ["/tmp", str(short_tmp)]  # noqa: S108 - Expected fallback path in the temp-directory probe test.
        assert len(bound_paths) == 1
        assert bound_paths[0].startswith(str(short_tmp))
        assert len(os.fsencode(bound_paths[0])) < 104
    finally:
        shutil.rmtree(short_tmp)


def test_unix_probe_skips_when_all_short_temp_directory_creation_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probes = _conftest_module()

    def denied_mkdtemp(
        suffix: str | None = None, prefix: str | None = None, dir: str | None = None
    ) -> str:
        raise PermissionError(errno.EPERM, "Operation not permitted", dir)

    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(probes.tempfile, "mkdtemp", denied_mkdtemp)
    with pytest.raises(probes._UnixBindDenied, match="temporary directory"):
        probes._probe_unix_bind(lambda path: None)


@pytest.mark.parametrize(
    "message",
    [
        (
            "bootstrap_check_in "
            "org.chromium.Chromium.MachPortRendezvousServer.1: Permission denied"
        ),
        "Operation not permitted",
    ],
)
def test_browser_launch_uses_single_process_args_and_propagates_errors(
    message: str,
) -> None:
    probes = _conftest_module()
    calls: list[list[str]] = []

    class Browser:
        def close(self) -> None:
            pass

    def launch(*, args: list[str]) -> Browser:
        calls.append(args)
        raise RuntimeError(message)

    with pytest.raises(RuntimeError, match=message):
        probes._probe_browser_launch(launch)
    assert calls == [["--single-process", "--no-zygote", "--disable-gpu"]]
    with pytest.raises(RuntimeError, match="Executable doesn't exist"):
        probes._run_probe(
            lambda: probes._probe_browser_launch(
                lambda **kwargs: _raise(
                    RuntimeError("Executable doesn't exist at browser path")
                )
            ),
            lambda error: False,
            "Chromium launch failed",
        )
