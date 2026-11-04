"""Resolve command words to module routes without importing those modules."""

from collections.abc import Sequence

from varde.rewrites import rewrite_rules_diff, rewrite_scan_setup, rewrite_seed_rule_id
from varde.routes import ROUTES, Route


def _has_prefix(words: Sequence[str], prefix: tuple[str, ...]) -> bool:
    return len(words) >= len(prefix) and tuple(words[: len(prefix)]) == prefix


def _child_names(prefix: tuple[str, ...]) -> set[str]:
    return {
        route.path[len(prefix)]
        for route in ROUTES
        if len(route.path) > len(prefix) and route.path[: len(prefix)] == prefix
    }


def _matches(route: Route, words: Sequence[str]) -> bool:
    if not _has_prefix(words, route.path):
        return False
    next_word = words[len(route.path)] if len(words) > len(route.path) else None
    return next_word not in route.deny


def _forwarded_argv(route: Route, tail: list[str]) -> list[str]:
    """Build module argv, applying route rewrites and the module's argv contract."""
    if route.path == ("scan", "rules", "diff"):
        rewritten = rewrite_rules_diff(tail)
        if rewritten is not None:
            tail = rewritten
    elif route.path == ("scan", "setup"):
        if not tail or tail[0] not in ("--help", "-h"):
            rewritten = rewrite_scan_setup(tail)
            if rewritten is not None:
                tail = rewritten
    elif route.path == ("scan", "rules", "seed"):
        rewritten = rewrite_seed_rule_id(tail)
        if rewritten is not None:
            tail = rewritten

    argv0_path = route.path[:-1] if route.legacy else route.path
    argv0 = "varde" if not argv0_path else f"varde {' '.join(argv0_path)}"
    module_args = [*route.legacy, *tail]
    if route.path == ("plan",):
        return ["plan", *module_args]
    if route.module in {"workflow", "learn", "design"}:
        return module_args
    return [argv0, *module_args]


def resolve(argv: Sequence[str]) -> tuple[Route, list[str]] | None:
    """Return the longest allowed route and its module argv, or ``None``.

    ``argv`` contains command arguments without the executable name. Returned
    module argv follows the routed module's contract, including argv0 only for
    modules that use it.
    """
    route = max(
        (r for r in ROUTES if _matches(r, argv)),
        key=lambda r: len(r.path),
        default=None,
    )
    if route is None:
        return None
    return route, _forwarded_argv(route, list(argv[len(route.path) :]))


def denied_route(argv: Sequence[str]) -> tuple[Route, str] | None:
    """Return the longest route whose next word is explicitly denied."""
    candidates = [
        route
        for route in ROUTES
        if _has_prefix(argv, route.path)
        and len(argv) > len(route.path)
        and argv[len(route.path)] in route.deny
        and argv[len(route.path)] not in _child_names(route.path)
    ]
    if not candidates:
        return None
    route = max(candidates, key=lambda item: len(item.path))
    return route, argv[len(route.path)]
