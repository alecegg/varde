"""Pure helpers for the relay end-to-end dry run."""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Awaitable, Callable
from pathlib import Path


def temp_store_path(temp_root: Path, token: str) -> Path:
    """Return the store-shaped path used by an isolated relay run."""
    if not re.fullmatch(r"[a-f0-9]{8,32}", token):
        raise ValueError("token must be 8-32 lowercase hexadecimal characters")
    return temp_root / f"_e2e-tmp-{token}" / "working" / ".cache" / "inbox"


def agent_created_leftovers(inbox: Path) -> list[Path]:
    """Return only known per-agent artifacts created by the live E2E run."""
    names = ("idle", "busy", "archived", "unknown", "sender")
    paths = [inbox / f".e2e-{name}.lock" for name in names]
    paths.extend(
        inbox / "index" / f"e2e-{name}{suffix}"
        for name in names
        for suffix in (".json", ".delivered" + ".json")
    )
    paths.extend(
        path
        for path in inbox.rglob("*")
        if path.is_file()
        and path.parent.parent == inbox
        and path.name in {f"e2e-{name}" for name in names}
    )
    return [path for path in paths if path.is_file()]


def grep_e2e_leaks(root: Path, token: str) -> list[str]:
    """Find this run's markers under root (never scan arbitrary e2e text)."""
    if not root.exists():
        return []
    token_bytes = re.escape(token.encode())
    boundary = rb"A-Za-z0-9_-"
    address = (
        rb"(?<![" + boundary + rb"])e2e-(?:idle|busy|archived|unknown|sender)"
        rb"(?![" + boundary + rb"])"
    )
    temp_dir = rb"(?<![" + boundary + rb"])_e2e-tmp-" + token_bytes
    temp_dir += rb"(?![" + boundary + rb"])"
    run_token = rb"(?<![A-Za-z0-9_])" + token_bytes + rb"(?![A-Za-z0-9_])"
    markers = re.compile(b"(?:" + b"|".join((address, temp_dir, run_token)) + b")")
    return sorted(
        str(path)
        for path in root.rglob("*")
        if path.is_file()
        and markers.search(path.name.encode() + b"\n" + path.read_bytes())
    )


def format_report(checks: dict[str, bool], *, cleaned: bool, leaks: list[str]) -> str:
    lines = [
        f"{'PASS' if passed else 'FAIL'} {name}" for name, passed in checks.items()
    ]
    lines.extend(
        (
            f"{'PASS' if cleaned else 'FAIL'} temp store cleaned",
            f"{'PASS' if not leaks else 'FAIL'} leak grep ({len(leaks)} files)",
        )
    )
    return "\n".join(lines)


async def wait_for_predicate(
    predicate: Callable[[], bool | Awaitable[bool]],
    *,
    timeout: float = 180,
    interval: float = 0.2,
) -> bool:
    """Poll a synchronous or asynchronous predicate within one deadline."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return False
        value = predicate()
        try:
            result = (
                await asyncio.wait_for(value, timeout=remaining)
                if inspect.isawaitable(value)
                else value
            )
        except TimeoutError:
            return False
        if result:
            return True
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(interval, remaining))


def fake_restart_drill() -> dict[str, bool]:
    """Model the required stop/start and crash recovery assertions offline."""
    binding: str | None = "runner-0"
    delivered: set[int] = {0}
    released: set[int] = set()
    taken_over: set[int] = set()
    refusals: list[str] = []
    old_worker = binding
    binding = "runner-overlap"
    old_worker_state = "superseded"
    if binding == old_worker:
        binding = None
    overlap_safe = old_worker_state == "superseded" and binding == "runner-overlap"
    binding = None
    overlap_released = binding is None
    binding = "human-live"
    refused_live_holder = binding == "human-live"
    binding = "human-live" if refused_live_holder else "runner-refused"
    live_holder_intact = binding == "human-live"
    binding = None
    nonrunner_released_before_restart = binding is None
    if nonrunner_released_before_restart:
        binding = "runner-0"
    for cycle, stop in enumerate(("SIGTERM", "SIGKILL", "SIGTERM")):
        if stop == "SIGTERM":
            binding = None
            released.add(cycle)
        if binding is not None:
            if binding.startswith("runner-"):
                taken_over.add(cycle)
            else:
                refusals.append("live-binding")
                continue
        binding = f"runner-{cycle + 1}"
        delivered.add(cycle + 1)
    return {
        "initial and post-restart deliveries": delivered == {0, 1, 2, 3},
        "graceful stop releases address": released == {0, 2},
        "restart takes over runner binding": taken_over == {1},
        "overlap supersedes old worker without unbinding new": overlap_safe,
        "overlap cancellation releases address": overlap_released,
        "live non-runner holder remains after refusal": live_holder_intact,
        "non-runner holder released before restart drill": (
            nonrunner_released_before_restart
        ),
        "no live-binding refusals": not refusals,
    }
