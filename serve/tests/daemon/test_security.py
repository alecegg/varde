import stat
from pathlib import Path

import pytest
from varde_serve.daemon.config import (
    ServeConfig,
    bind_refusal,
    load_serve_config,
    parse_serve_table,
)
from varde_serve.daemon.security import (
    FailureLimiter,
    PerClientLimiter,
    RouteClass,
    Scope,
    allowed_hosts,
    host_ok,
    origin_ok,
    route_class,
    scope_denied,
    token_scope,
    write_denied,
)
from varde_serve.daemon.tokens import ensure_tokens, state_dir, token_file_mode


def test_route_classes() -> None:
    assert route_class("GET", "/health") is RouteClass.PUBLIC
    assert route_class("GET", "/api/plans") is RouteClass.READ
    assert route_class("GET", "/api/events") is RouteClass.READ
    assert route_class("POST", "/auth/session") is RouteClass.PUBLIC
    assert route_class("POST", "/anything/new") is RouteClass.HUMAN_WRITE


def test_write_denied_orders_token_before_edit_gate() -> None:
    assert write_denied("/api/x", token_ok=False, allow_edit=True) == "unauthorized"
    assert write_denied("/api/x", token_ok=True, allow_edit=False) == "edit_disabled"
    assert write_denied("/api/x", token_ok=True, allow_edit=True) is None
    assert write_denied("/shutdown", token_ok=True, allow_edit=False) is None
    assert write_denied("/auth/session", token_ok=False, allow_edit=False) is None


def test_mcp_scope_never_reaches_human_write() -> None:
    assert scope_denied(RouteClass.HUMAN_WRITE, Scope.MCP)
    assert not scope_denied(RouteClass.HUMAN_WRITE, Scope.HUMAN)
    assert not scope_denied(RouteClass.AGENT_WRITE, Scope.MCP)


def test_token_scope_compares_both_tokens() -> None:
    assert token_scope("h", "h", "m") is Scope.HUMAN
    assert token_scope("m", "h", "m") is Scope.MCP
    assert token_scope("x", "h", "m") is None
    assert token_scope("", "h", "m") is None


def test_host_and_origin_allowlist() -> None:
    allowed = allowed_hosts(8000, ("tail.example:8000",))
    assert host_ok("127.0.0.1:8000", allowed)
    assert host_ok("localhost:8000", allowed)
    assert not host_ok("evil.example", allowed)
    assert not host_ok(None, allowed)
    assert origin_ok(None, allowed)
    assert origin_ok("http://localhost:8000", allowed)
    assert not origin_ok("http://evil.example", allowed)


def test_failure_limiter_blocks_after_limit_then_recovers() -> None:
    now = [0.0]
    limiter = FailureLimiter(limit=2, window_s=60, clock=lambda: now[0])
    limiter.record_failure()
    assert not limiter.blocked()
    limiter.record_failure()
    assert limiter.blocked()
    now[0] = 61
    assert not limiter.blocked()


def test_bind_refusal_needs_config() -> None:
    assert bind_refusal(ServeConfig(), None) is None
    assert bind_refusal(ServeConfig(), "127.0.0.1") is None
    assert bind_refusal(ServeConfig(), "0.0.0.0") is not None  # noqa: S104
    assert bind_refusal(ServeConfig(bind="100.64.0.1"), "100.64.0.1") is None


def test_serve_table_validation(tmp_path: Path) -> None:
    assert parse_serve_table({"allow_edit": True}).allow_edit
    with pytest.raises(ValueError, match="port"):
        parse_serve_table({"port": 70000})
    (tmp_path / "config.toml").write_text("[serve]\nallow_edit = true\nport = 7\n")
    assert load_serve_config(tmp_path) == ServeConfig(port=7, allow_edit=True)


def test_token_files_are_owner_only(tmp_path: Path) -> None:
    tokens = ensure_tokens(tmp_path)
    directory = state_dir(tmp_path)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert token_file_mode(directory / "token") == 0o600
    assert token_file_mode(directory / "mcp-token") == 0o600
    assert tokens.human != tokens.mcp
    assert ensure_tokens(tmp_path) == tokens


def test_per_client_limiter_isolates_clients_and_bounds_memory() -> None:
    now = [0.0]
    limiter = PerClientLimiter(
        limit=2, window_s=60, clock=lambda: now[0], max_clients=2
    )
    limiter.record_failure("a")
    limiter.record_failure("a")
    assert limiter.blocked("a")
    assert not limiter.blocked("b")  # one client's failures never lock out another
    limiter.record_failure("b")
    limiter.record_failure("c")  # evicts the oldest client ("a")
    assert not limiter.blocked("a")
