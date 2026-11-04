from __future__ import annotations

import errno
import json
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from stop_server import stop_server
from store_guard import assert_inbox_unchanged, resolve_real_inbox_root, snapshot_inbox
from varde_runner import GRACEFUL_SHUTDOWN_TIMEOUT
from varde_runner.plans_repository import clear_shared_plans_repositories


def _run_probe(probe, sandbox_denial, reason: str) -> None:
    try:
        probe()
    except Exception as exc:
        if sandbox_denial(exc):
            pytest.skip(f"{reason}: {exc}")
        raise


class _UnixBindDenied(Exception):
    pass


RUN_PREFIX = f"vrt-{uuid.uuid4().hex[:12]}-"
BROWSER_ARGS = ["--single-process", "--no-zygote", "--disable-gpu"]
RUNNER_ROOT = Path(__file__).parents[1]
SERVER_SHUTDOWN_TIMEOUT = GRACEFUL_SHUTDOWN_TIMEOUT + 5
RUNNER_UI_SKIP_REASON = "runner UI not built; run just build-ui"


def _is_unix_sandbox_denial(error: Exception) -> bool:
    return isinstance(error, _UnixBindDenied)


def _probe_unix_bind(bind: Callable[[str], None] | None = None) -> None:
    candidates = list(dict.fromkeys(("/tmp", os.environ.get("TMPDIR"))))  # noqa: S108 - Probe intentionally tests the conventional temporary directory.
    denied: list[str] = []
    for base in candidates:
        if not base:
            continue
        try:
            directory = tempfile.mkdtemp(prefix="v", dir=base)
        except OSError as exc:
            if isinstance(exc, PermissionError) or exc.errno == errno.EPERM:
                denied.append(f"{base}: {exc}")
                continue
            raise

        path = Path(directory) / "s"
        if len(os.fsencode(path)) >= 104:
            shutil.rmtree(directory, ignore_errors=True)
            continue

        listener = None
        try:
            bind_path = bind
            if bind_path is None:
                listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                bind_path = listener.bind
            try:
                bind_path(str(path))
            except OSError as exc:
                if isinstance(exc, PermissionError) or exc.errno == errno.EPERM:
                    raise _UnixBindDenied(f"socket bind denied: {exc}") from exc
                raise
            return
        finally:
            if listener is not None:
                listener.close()
            shutil.rmtree(directory, ignore_errors=True)

    if denied:
        details = "; ".join(denied)
        raise _UnixBindDenied(f"temporary directory creation denied ({details})")
    raise _UnixBindDenied(
        "no short AF_UNIX temp directory under /tmp or $TMPDIR (<104 bytes)"
    )


def _probe_browser_launch(launch: Callable[..., Any]) -> Any:
    return _launch_browser(launch)


def _launch_browser(launch: Callable[..., Any]) -> Any:
    return launch(args=BROWSER_ARGS)


def _runner_ui_built() -> bool:
    ui_dir = RUNNER_ROOT / "src" / "varde_runner" / "web" / "static" / "ui"
    return (ui_dir / "index.html").is_file() and (ui_dir / "_app").is_dir()


def _browser_launch_error(error: Exception) -> str:
    browser_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not browser_root:
        browser_root = str(
            Path.home()
            / (
                "Library/Caches/ms-playwright"
                if platform.system() == "Darwin"
                else ".cache/ms-playwright"
            )
        )
    if browser_root == "0":
        browser_root = "the Playwright package-local browser directory"
    return (
        "Runner browser tests require Playwright Chromium. From the repo root, "
        "run `uv run playwright install chromium`. If Chromium is already "
        "installed but unreadable in a sandbox, grant filesystem allowRead for "
        f"the Playwright browser cache at {browser_root}. "
        f"Browser launch failed: {error}"
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if not shutil.which("node"):
        skip_node_tests = pytest.mark.skip(reason="node is not on PATH")
        for item in items:
            if "node_host" in str(item.fspath):
                item.add_marker(skip_node_tests)

    browser_timeout = pytest.mark.timeout(60)
    for item in items:
        is_browser_test = item.fspath.basename.endswith("_browser.py") or (
            item.fspath.basename == "test_web_browser.py"
        )
        if is_browser_test:
            item.add_marker(browser_timeout)

    if os.environ.get("VARDE_RUNNER_PASEO_LIVE") == "1" and any(
        item.name == "test_real_paseo_daemon_contract" for item in items
    ):
        client = RUNNER_ROOT / "sidecar" / "node_modules" / "@getpaseo" / "client"
        if not client.is_dir():
            pytest.exit(
                "The live Paseo adapter test requires sidecar dependencies. From "
                "the repo root, run `npm ci --prefix runner/sidecar`.",
                returncode=4,
            )


@pytest.fixture(scope="session")
def require_unix_socket() -> None:
    _run_probe(
        _probe_unix_bind,
        _is_unix_sandbox_denial,
        "AF_UNIX socket bind denied by sandbox",
    )


@pytest.fixture(scope="session")
def runner_ui_built() -> None:
    if not _runner_ui_built():
        pytest.skip(RUNNER_UI_SKIP_REASON)


@pytest.fixture(scope="session")
def browser_prerequisites(runner_ui_built: None) -> None:

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
    except (ImportError, OSError) as exc:
        pytest.fail(
            "Runner browser tests require Playwright Python dependencies. From "
            f"the repo root, run `uv sync --group dev`. Error: {exc}",
            pytrace=False,
        )

    try:
        browser = _launch_browser(playwright.chromium.launch)
    except (OSError, PlaywrightError) as exc:
        pytest.fail(_browser_launch_error(exc), pytrace=False)
    else:
        browser.close()
    finally:
        playwright.stop()


@pytest.fixture(scope="module")
def browser_session(browser_prerequisites: None) -> Iterator[Any]:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        browser = _launch_browser(playwright.chromium.launch)
    except (OSError, PlaywrightError) as exc:
        playwright.stop()
        pytest.fail(_browser_launch_error(exc), pytrace=False)
    try:
        yield browser
        if not browser.is_connected():
            raise RuntimeError("Shared Chromium disconnected before module teardown")
        browser.close()
    finally:
        playwright.stop()


@pytest.fixture(scope="module")
def shared_browser_page(browser_session: Any) -> Iterator[Any]:
    from playwright.sync_api import expect

    page = browser_session.new_page(viewport={"width": 390, "height": 844})
    page.set_default_timeout(10_000)
    expect.set_options(timeout=10_000)
    yield page


@pytest.fixture(scope="session")
def browser_screenshot_dir() -> Path:
    directory = Path(
        os.environ.get("VARDE_C1A_SCREENSHOT_DIR")
        or Path(os.environ.get("TMPDIR", tempfile.gettempdir())) / "pytest-browser"
    )
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@pytest.fixture
def browser_server(
    request: pytest.FixtureRequest, shared_browser_page: Any
) -> Callable[[Any], str]:
    def start(app: Any) -> str:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="error",
                access_log=False,
                lifespan="off",
                # test_server_shutdown.py covers graceful shutdown.
                timeout_graceful_shutdown=0,
            )
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        def stop() -> None:
            shared_browser_page.goto("about:blank")
            stop_server(server, thread)

        request.addfinalizer(stop)
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        return f"http://127.0.0.1:{port}"

    return start


@pytest.fixture(scope="session", autouse=True)
def real_inbox_store_guard() -> Iterator[None]:
    root = resolve_real_inbox_root()
    before = snapshot_inbox(root)
    yield
    assert_inbox_unchanged(root, before, run_prefix=RUN_PREFIX)


@pytest.fixture(scope="session", autouse=True)
def runner_cli_sandbox(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    root = tmp_path_factory.mktemp("varde-runner-cli")
    for name in ("home", "config", "xdg-config", "xdg-cache", "xdg-data", "working"):
        (root / name).mkdir()
    browser_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not browser_path:
        browser_path = str(
            Path.home()
            / (
                "Library/Caches/ms-playwright"
                if platform.system() == "Darwin"
                else ".cache/ms-playwright"
            )
        )
    keys = (
        "HOME",
        "VARDE_CONFIG_DIR",
        "VARDE_WORKING_DIR",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "PLAYWRIGHT_BROWSERS_PATH",
        "VARDE_TEST_RUN_PREFIX",
    )
    original = {key: os.environ.get(key) for key in keys}
    original_cwd = Path.cwd()
    os.environ.update(
        {
            "HOME": str(root / "home"),
            "VARDE_CONFIG_DIR": str(root / "config"),
            "VARDE_WORKING_DIR": str(root / "working"),
            "XDG_CONFIG_HOME": str(root / "xdg-config"),
            "XDG_CACHE_HOME": str(root / "xdg-cache"),
            "XDG_DATA_HOME": str(root / "xdg-data"),
            "PLAYWRIGHT_BROWSERS_PATH": browser_path,
            "VARDE_TEST_RUN_PREFIX": RUN_PREFIX,
        }
    )
    try:
        git_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],  # noqa: S607 - Git is resolved from PATH to locate the checkout.
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        assert git_root.returncode != 0, (
            "CLI sandbox unexpectedly resolves inside a repository"
        )
        result = subprocess.run(
            ["varde", "setup", "paths", "--json"],  # noqa: S607 - Test uses the installed Varde CLI from PATH.
            cwd=root,
            env=os.environ.copy(),
            capture_output=True,
            check=True,
            text=True,
        )
        paths = json.loads(result.stdout)["data"]
        working = Path(paths["working"]).resolve()
        assert working.is_relative_to(root.resolve())
        yield root
    finally:
        os.chdir(original_cwd)
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture(autouse=True)
def runner_test_cli_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("xdg-config", "xdg-cache", "xdg-data"):
        (tmp_path / name).mkdir(exist_ok=True)
    isolated_working = tmp_path / "isolated-varde-working"
    isolated_working.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("VARDE_WORKING_DIR", str(isolated_working))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.setenv(
        "PLAYWRIGHT_BROWSERS_PATH", os.environ["PLAYWRIGHT_BROWSERS_PATH"]
    )
    monkeypatch.setenv("VARDE_TEST_RUN_PREFIX", RUN_PREFIX)


@pytest.fixture(autouse=True)
def clear_plan_repository_registry() -> Iterator[None]:
    clear_shared_plans_repositories()
    yield
    clear_shared_plans_repositories()


@pytest.fixture
def sidecar_package() -> dict[str, object]:
    package_path = Path(__file__).parents[1] / "sidecar" / "package.json"
    return json.loads(package_path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _hermetic_paseo_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests from spawning the real Paseo node sidecar.

    Without this, tests pass or fail depending on whether
    runner/sidecar/node_modules is installed. Set VARDE_RUNNER_PASEO_LIVE=1
    to use the real plugin.
    """
    if os.environ.get("VARDE_RUNNER_PASEO_LIVE") == "1":
        return
    from varde_runner.plugins.paseo import PaseoPlugin

    class _DisabledPaseoPlugin(PaseoPlugin):
        async def _ensure_started(self) -> None:
            raise RuntimeError("Paseo sidecar disabled in tests")

    real_from_environment = PaseoPlugin.from_environment.__func__

    def from_environment(_cls: type[PaseoPlugin]) -> PaseoPlugin:
        return real_from_environment(_DisabledPaseoPlugin)

    monkeypatch.setattr(PaseoPlugin, "from_environment", classmethod(from_environment))
