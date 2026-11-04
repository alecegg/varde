import importlib.util
import os
import subprocess
import sys
import threading
from argparse import Namespace
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "deploy.py"
spec = importlib.util.spec_from_file_location("varde_deploy", SCRIPT)
assert spec is not None and spec.loader is not None
deploy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = deploy
spec.loader.exec_module(deploy)

FAKE_UV = """#!/bin/sh
[ "$FAKE_MODE" = install-fails ] && { echo "failed to remove directory" >&2; exit 2; }
mkdir -p "$UV_TOOL_BIN_DIR"
if [ "$FAKE_MODE" = smoke-fails ]; then body='exit 1'; else body='echo "varde 9.9"'; fi
printf '#!/bin/sh\\n%s\\n' "$body" > "$UV_TOOL_BIN_DIR/varde"
chmod +x "$UV_TOOL_BIN_DIR/varde"
"""


@pytest.fixture
def layout(tmp_path, monkeypatch):
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text(FAKE_UV)
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    link = tmp_path / "bin" / "varde"
    releases = tmp_path / "releases"
    old = tmp_path / "old" / "varde"
    old.parent.mkdir()
    old.write_text('#!/bin/sh\necho "varde 1.0"\n')
    old.chmod(0o755)
    link.parent.mkdir()
    link.symlink_to(old)
    monkeypatch.setattr(
        deploy, "verify_installed_sources", lambda *_args: "verified fixture sources"
    )
    return Namespace(link=link, releases=releases, app=tmp_path / "app", old=old)


def swap(layout, stamp="1"):
    return deploy.swap_cli(layout.app, layout.releases, layout.link, "abc", stamp)


def version(link):
    return subprocess.run(  # noqa: S603
        [str(link), "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_swap_repoints_after_smoke(layout):
    detail = swap(layout)
    assert version(layout.link) == "varde 9.9"
    assert str(layout.old) in detail
    assert "verified fixture sources" in detail


def test_install_release_reinstalls_cached_workspace_packages(monkeypatch, tmp_path):
    commands = []
    executable = tmp_path / "release" / "bin" / "varde"

    def fake_run(command, _env=None):
        commands.append(command)
        executable.parent.mkdir(parents=True)
        executable.touch()
        return ""

    monkeypatch.setattr(deploy, "run_checked", fake_run)
    assert (
        deploy.install_release(tmp_path / "release", tmp_path / "source") == executable
    )
    assert commands[0][:4] == ["uv", "tool", "install", "--force"]
    assert "--reinstall" in commands[0]


def test_verify_installed_sources_compares_package_contents(tmp_path):
    source = tmp_path / "source"
    package = source / "workflow" / "src" / "varde_workflow"
    package.mkdir(parents=True)
    (source / "pyproject.toml").write_text(
        '[tool.uv.workspace]\nmembers = ["workflow"]\n', encoding="utf-8"
    )
    source_file = package / "cli.py"
    source_file.write_text("fresh source", encoding="utf-8")
    installed_package = (
        tmp_path
        / "release"
        / "tools"
        / "varde"
        / "lib"
        / "python3.14"
        / "site-packages"
        / "varde_workflow"
    )
    installed_package.mkdir(parents=True)
    installed_file = installed_package / "cli.py"
    installed_file.write_text("stale source", encoding="utf-8")

    with pytest.raises(RuntimeError, match="varde_workflow/cli.py"):
        deploy.verify_installed_sources(tmp_path / "release", source)

    installed_file.write_text("fresh source", encoding="utf-8")
    assert deploy.verify_installed_sources(tmp_path / "release", source) == (
        "verified 1 workspace Python source files"
    )


@pytest.mark.parametrize("mode", ["install-fails", "smoke-fails"])
def test_failed_install_leaves_previous_cli(layout, monkeypatch, mode):
    monkeypatch.setenv("FAKE_MODE", mode)
    with pytest.raises(RuntimeError):
        swap(layout)
    assert version(layout.link) == "varde 1.0"
    assert not list(layout.releases.glob("*"))


def test_stale_install_leaves_previous_cli(layout, monkeypatch):
    def reject_stale_release(*_args):
        raise RuntimeError("stale install")

    monkeypatch.setattr(deploy, "verify_installed_sources", reject_stale_release)
    with pytest.raises(RuntimeError, match="stale install"):
        swap(layout)
    assert version(layout.link) == "varde 1.0"
    assert not list(layout.releases.glob("*"))


def test_version_never_fails_during_swaps(layout):
    failures = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            done = subprocess.run(  # noqa: S603
                [str(layout.link), "--version"], capture_output=True, check=False
            )
            if done.returncode != 0:
                failures.append(done.stderr)

    thread = threading.Thread(target=reader)
    thread.start()
    try:
        for index in range(15):
            swap(layout, stamp=str(index))
    finally:
        stop.set()
        thread.join()
    assert failures == []


def test_repoint_refuses_regular_file(tmp_path):
    link = tmp_path / "varde"
    link.write_text("x")
    with pytest.raises(RuntimeError):
        deploy.repoint(link, tmp_path / "target")


def test_prune_keeps_newest_and_protected(tmp_path):
    releases = tmp_path / "releases"
    for name in ("1-a", "2-a", "3-a", "4-a"):
        (releases / name / "bin").mkdir(parents=True)
    removed = deploy.prune_releases(releases, 2, {releases / "1-a" / "bin"})
    assert [p.name for p in removed] == ["2-a"]
    assert sorted(p.name for p in releases.iterdir()) == ["1-a", "3-a", "4-a"]


def test_prune_keeps_at_least_two(tmp_path):
    releases = tmp_path / "releases"
    for name in ("1-a", "2-a", "3-a"):
        (releases / name).mkdir(parents=True)
    deploy.prune_releases(releases, 1, set())
    assert sorted(p.name for p in releases.iterdir()) == ["2-a", "3-a"]


def test_ui_stale_detection(tmp_path):
    index = tmp_path / "index.html"
    source = tmp_path / "src"
    source.mkdir()
    (source / "a.svelte").write_text("a")
    assert deploy.ui_is_stale(index, (source,))
    index.write_text("built")
    os.utime(source / "a.svelte", (1, 1))
    assert not deploy.ui_is_stale(index, (source,))
    os.utime(source / "a.svelte", (index.stat().st_mtime + 10,) * 2)
    assert deploy.ui_is_stale(index, (source,))


@pytest.mark.parametrize(
    "cli_error", [deploy.StepWarning("warn"), RuntimeError("boom")]
)
def test_runner_restart_runs_after_cli_problem(
    monkeypatch, tmp_path, capsys, cli_error
):
    calls = []

    def bad_swap(*_args):
        raise cli_error

    monkeypatch.setattr(deploy, "swap_cli", bad_swap)
    monkeypatch.setattr(deploy, "git_commit", lambda: "abc")
    monkeypatch.setattr(deploy, "build_ui", lambda: "skipped")
    monkeypatch.setattr(deploy, "wait_relay_idle", lambda *_: "idle")
    monkeypatch.setattr(deploy, "service", lambda action: calls.append(action) or "ok")
    monkeypatch.setattr(deploy, "wait_runner_ready", lambda *_: "ready")
    monkeypatch.setattr(deploy, "check_endpoints", lambda _p: "/ 200 0.01s")
    args = deploy.parser().parse_args(
        ["--releases", str(tmp_path), "--link", str(tmp_path / "v")]
    )
    code = deploy.deploy(args)
    out = capsys.readouterr().out
    assert calls == ["stop", "start"]
    for step in ("cli-swap", "ui-build", "runner-start", "endpoints"):
        assert step in out
    assert code == (1 if isinstance(cli_error, RuntimeError) else 0)


def test_service_runs_supported_entry_point(monkeypatch):
    commands = []
    monkeypatch.setattr(
        deploy, "run_checked", lambda command, env=None: commands.append(command) or ""
    )
    assert deploy.service("stop") == "stop sent"
    runner = str(deploy.ROOT / "runner")
    assert commands == [
        ["uv", "run", "--project", runner, "varde-runner", "service", "stop"]
    ]


def test_deploy_has_no_system_python_shim():
    assert not SCRIPT.with_name("runner-service.py").exists()


def test_install_release_installs_the_named_package(monkeypatch, tmp_path):
    commands = []
    executable = tmp_path / "release" / "bin" / "varde-serve"

    def fake_run(command, _env=None):
        commands.append(command)
        executable.parent.mkdir(parents=True)
        executable.touch()
        return ""

    monkeypatch.setattr(deploy, "run_checked", fake_run)
    found = deploy.install_release(
        tmp_path / "release", tmp_path / "serve", "varde-serve"
    )
    assert found == executable
    assert commands[0][-1] == "varde-serve"


def run_serve_step(monkeypatch, tmp_path, *extra):
    calls = []
    monkeypatch.setattr(deploy, "swap_cli", lambda *a: calls.append(a) or "ok")
    monkeypatch.setattr(deploy, "git_commit", lambda: "abc")
    args = deploy.parser().parse_args(
        [
            "--skip-cli",
            "--skip-ui",
            "--skip-runner",
            "--serve-releases",
            str(tmp_path / "rel"),
            "--serve-link",
            str(tmp_path / "bin" / "varde-serve"),
            *extra,
        ]
    )
    assert deploy.deploy(args) == 0
    return calls


def test_deploy_installs_varde_serve_from_its_own_source(monkeypatch, tmp_path):
    (call,) = run_serve_step(monkeypatch, tmp_path)
    source, releases, link, _commit, _stamp, package, smoke = call
    assert source == deploy.ROOT / "serve"
    assert releases == tmp_path / "rel"
    assert link == tmp_path / "bin" / "varde-serve"
    assert (package, smoke) == ("varde-serve", (["--version"],))


def test_skip_serve_leaves_varde_serve_alone(monkeypatch, tmp_path):
    assert run_serve_step(monkeypatch, tmp_path, "--skip-serve") == []
