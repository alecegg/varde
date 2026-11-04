"""Every mutating route's class is the one its definition declares."""

from pathlib import Path

import pytest
from starlette.routing import Route
from varde_serve.api.routes import api_routes
from varde_serve.daemon.app import DaemonContext
from varde_serve.daemon.config import ServeConfig
from varde_serve.daemon.security import WRITE_METHODS, RouteClass, route_class
from varde_serve.daemon.tokens import Tokens
from varde_serve.project import Project

AGENT, HUMAN = RouteClass.AGENT_WRITE, RouteClass.HUMAN_WRITE
EXPECTED = {
    ("POST", "/api/queue/reorder"): HUMAN,
    ("POST", "/api/friction"): AGENT,
    ("POST", "/api/docs/{path:path}/comments/{cid}/replies"): AGENT,
    ("POST", "/api/docs/{path:path}/comments"): AGENT,
    ("POST", "/api/docs/{path:path}/decisions/{did}"): HUMAN,
    ("POST", "/api/mail"): AGENT,
    ("PUT", "/api/config/{key}"): HUMAN,
}


@pytest.fixture
def routes(tmp_path: Path) -> list[Route]:
    ctx = DaemonContext(ServeConfig(), Tokens("h", "m"), "t", 1, static_dir=tmp_path)
    project = Project(tmp_path / "cfg", tmp_path, tmp_path)
    return [r for r in api_routes(ctx, project) if isinstance(r, Route)]


def sample(template: str) -> str:
    return (
        template.replace("{path:path}", "notes/a.md")
        .replace("{cid}", "c1")
        .replace("{did}", "d1")
        .replace("{key}", "orchestration.stall_minutes")
    )


def test_every_mutating_route_has_an_expected_class(routes: list[Route]) -> None:
    mutating = {
        (method, route.path)
        for route in routes
        for method in (route.methods or ())
        if method in WRITE_METHODS
    }
    assert mutating == set(EXPECTED), "a new write route needs an explicit class here"


def test_gate_class_matches_the_declared_class(routes: list[Route]) -> None:
    for (method, template), expected in EXPECTED.items():
        assert route_class(method, sample(template)) is expected, template


@pytest.mark.parametrize(
    "path",
    [
        "/api/docs/a.md/comments/c1/x",  # not an agent route: falls to human-write
        "/api/docs/a.md/comments/c1",
        "/api/docs/a.md/decisions",
        "/api/docs/a.md/comments/",
    ],
)
def test_lookalike_paths_fail_closed_to_human_write(
    routes: list[Route], path: str
) -> None:
    assert route_class("POST", path) is HUMAN


def test_get_on_a_write_path_is_a_read(routes: list[Route]) -> None:
    assert route_class("GET", "/api/mail") is RouteClass.READ
