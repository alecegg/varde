"""Attach the project's watchers and API routes to a daemon context."""

from __future__ import annotations

from varde_serve.api.routes import api_routes
from varde_serve.daemon.app import DaemonContext
from varde_serve.events.watchers import doc_comment_watcher, plan_state_watcher
from varde_serve.project import Project


def wire(ctx: DaemonContext, project: Project) -> None:
    ctx.watchers += [
        doc_comment_watcher(project.working),
        plan_state_watcher(project.working),
    ]
    ctx.extra_routes += api_routes(ctx, project)
