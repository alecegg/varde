from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route
from varde_runner.bot_route_policy import (
    POLICY,
    Kind,
    classify,
    iter_route_keys,
    policy_for,
    unclassified_routes,
)
from varde_runner.user_credential import UserCredential
from varde_runner.web.app import create_app


@pytest.fixture
def real_app(tmp_path):
    return create_app(
        data_dir=tmp_path / "data",
        bound_port=8765,
        user_credential=UserCredential(tmp_path / "user-credential.json"),
    )


def test_every_route_of_the_real_app_is_classified(real_app) -> None:
    assert unclassified_routes(real_app.routes) == []
    for method, path, expected in (
        ("GET", "/chat/needs", Kind.READ),
        ("GET", "/settings/{section:str}", Kind.READ),
        ("GET", "/mailbox", Kind.USER_ONLY),
        ("GET", "/threads", Kind.USER_ONLY),
        ("GET", "/api/pins", Kind.USER_DATA),
        ("GET", "/api/plans", Kind.READ),
        (
            "POST",
            "/api/plans/{plan_id:str}/comments/{comment_id:str}",
            Kind.USER_ONLY,
        ),
        ("PUT", "/api/pins", Kind.USER_ONLY),
        ("GET", "/api/runner/config/toml", Kind.USER_DATA),
        ("POST", "/api/plans/{plan_id:path}/merge-approval/agent", Kind.USER_DATA),
        ("POST", "/api/runner/config/sdk-flip/preview", Kind.USER_ONLY),
        ("POST", "/api/runner/config/sdk-flip/apply", Kind.USER_ONLY),
        ("GET", "/approve", Kind.USER_ONLY),
    ):
        policy = policy_for(method, path)
        assert policy is not None
        assert policy.kind is expected


def test_the_table_has_no_entry_for_a_route_the_app_does_not_serve(real_app) -> None:
    served = set(iter_route_keys(real_app.routes))
    assert sorted(set(POLICY) - served) == []


def test_a_route_missing_from_the_table_is_reported() -> None:
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(
        routes=[Route("/api/queue", ok), Route("/api/brand-new", ok, methods=["POST"])]
    )
    assert unclassified_routes(app.routes) == [("POST", "/api/brand-new")]


def test_mounts_without_inner_routes_are_listed_as_get() -> None:
    app = Starlette(routes=[Mount("/static", app=PlainTextResponse("x"))])
    assert list(iter_route_keys(app.routes)) == [("GET", "/static")]
    assert unclassified_routes(app.routes) == []


def kind_of(app, method: str, path: str):
    policy = classify(app.routes, scope(method, path)).policy
    assert policy is not None
    return policy.kind


def scope(method: str, path: str) -> dict:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "root_path": "",
        "headers": [],
    }


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/chat/messages"),
        ("POST", "/api/instance-threads/a1/takeover"),
        ("POST", "/api/instance-threads/a1/takeover/heartbeat"),
        ("DELETE", "/api/instance-threads/a1/takeover"),
        ("POST", "/api/mailbox/d1/answer"),
        ("POST", "/api/mailbox/d1/dismiss"),
        ("POST", "/api/mailbox/d1/restore"),
        ("POST", "/mailbox/d1/answer"),
        ("POST", "/api/agents/a1/respond"),
        ("POST", "/api/agents/a1/mode"),
        ("POST", "/api/agents/a1/anything-else"),
        ("POST", "/api/roles/save"),
        ("POST", "/api/roles/preview"),
        ("POST", "/api/settings"),
        ("PUT", "/api/identities/i1"),
        ("POST", "/api/guard/revoke"),
        ("POST", "/api/guard/unrevoke"),
        ("PUT", "/api/jobs/j1/budget"),
        ("POST", "/api/jobs/j1/run"),
        ("POST", "/api/learn/sweep/run"),
        ("POST", "/api/orchestrators/o1/status"),
        ("POST", "/api/probe"),
        ("POST", "/entries/e1/retry"),
        ("POST", "/new-item"),
        ("POST", "/api/work-items/w1/decision"),
        ("POST", "/api/work-items/w1/plan-ready"),
        ("POST", "/api/workspaces"),
        ("DELETE", "/api/workspaces"),
    ],
)
def test_user_decisions_and_config_routes_are_user_only(real_app, method, path) -> None:
    classified = classify(real_app.routes, scope(method, path))
    assert classified.policy is not None
    assert classified.policy.kind == Kind.USER_ONLY, classified.route_key


@pytest.mark.parametrize(
    ("method", "path", "constraint"),
    [
        ("POST", "/api/agents", "launch"),
        ("POST", "/api/agents/a1/prompt", "agent_action"),
        ("POST", "/api/agents/a1/interrupt", "agent_action"),
        ("POST", "/api/agents/a1/resume", "agent_action"),
        ("POST", "/api/agents/a1/stop", "agent_action"),
        ("POST", "/api/agents/a1/archive", "agent_action"),
        ("POST", "/api/work-items", "stub"),
        ("POST", "/api/queue/move", "queue_move"),
        ("POST", "/api/plans/p1/comments", "plan_comment"),
        ("POST", "/api/bot/say", "bot_say"),
        ("POST", "/api/bot/notes", "bot_notes"),
        ("POST", "/api/bot/mailbox", "bot_mailbox"),
        ("PUT", "/api/plans/p1/body", "plan_edit"),
    ],
)
def test_the_allowlist_is_exactly_the_planned_actions(
    real_app, method, path, constraint
) -> None:
    classified = classify(real_app.routes, scope(method, path))
    assert classified.policy is not None
    assert (classified.policy.kind, classified.policy.constraint) == (
        Kind.ALLOW,
        constraint,
    )
    allowed = {key for key, value in POLICY.items() if value.kind == Kind.ALLOW}
    assert len(allowed) == 13


def test_get_routes_are_read_and_head_follows_get(real_app) -> None:
    for method, path in (
        ("GET", "/api/agents"),
        ("GET", "/chat/needs"),
        ("HEAD", "/api/agents"),
        ("GET", "/_app/x.js"),
        ("GET", "/api/bot/audit"),
        ("GET", "/chats"),
    ):
        assert kind_of(real_app, method, path) == Kind.READ
    assert policy_for("HEAD", "/api/queue") == policy_for("GET", "/api/queue")


def test_profile_route_exposes_user_data(real_app) -> None:
    assert kind_of(real_app, "GET", "/profile/builder-1") == Kind.USER_DATA


def test_unmatched_paths_and_wrong_methods_have_no_policy(real_app) -> None:
    for method, path in (
        ("GET", "/no/such/path"),
        ("DELETE", "/api/queue"),
        ("POST", "/_app/x.js"),
    ):
        assert classify(real_app.routes, scope(method, path)).policy is None


def test_a_mounted_route_with_an_allowlisted_child_path_stays_unclassified() -> None:
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(
        routes=[
            Route("/api/agents", ok, methods=["POST"]),
            Mount(
                "/extension",
                routes=[
                    Route("/api/agents", ok, methods=["POST"]),
                    Route("/api/queue/move", ok, methods=["POST"]),
                ],
            ),
        ]
    )
    top = classify(app.routes, scope("POST", "/api/agents"))
    mounted = classify(app.routes, scope("POST", "/extension/api/agents"))
    assert top.policy is not None and top.policy.kind == Kind.ALLOW
    assert mounted.policy is None
    assert mounted.route_key == "POST /extension/api/agents"
    assert (
        classify(app.routes, scope("POST", "/extension/api/queue/move")).policy is None
    )
    assert unclassified_routes(app.routes) == [
        ("POST", "/extension/api/agents"),
        ("POST", "/extension/api/queue/move"),
    ]


def test_a_mounted_get_route_does_not_inherit_a_read_policy() -> None:
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Mount("/x", routes=[Route("/api/queue", ok)])])
    assert classify(app.routes, scope("GET", "/x/api/queue")).policy is None
