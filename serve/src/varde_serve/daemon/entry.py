"""Start the daemon for the project in the current directory."""

from __future__ import annotations

from pathlib import Path

from varde_core.paths import varde_config_dir
from varde_learn.knowledge.memory import MemoryPaths

from varde_serve.daemon.lifecycle import run_daemon
from varde_serve.daemon.wiring import wire
from varde_serve.project import Project
from varde_serve.version import serve_version


def current_project() -> Project:
    here = Path.cwd()
    return Project(varde_config_dir(), MemoryPaths.resolve(here).working.path, here)


def run_here(requested_bind: str | None = None) -> int:
    project = current_project()
    return run_daemon(
        project.config_dir,
        serve_version(),
        requested_bind=requested_bind,
        configure=lambda ctx: wire(ctx, project),
    )
