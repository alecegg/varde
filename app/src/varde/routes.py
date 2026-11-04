"""Plain-data route table for the public and hidden ``varde`` commands."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Route:
    path: tuple[str, ...]
    module: str
    legacy: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()
    hidden: bool = False


def _route(
    path: tuple[str, ...],
    module: str,
    legacy: tuple[str, ...] = (),
    deny: tuple[str, ...] = (),
) -> Route:
    return Route(path, module, legacy, deny)


ROUTES = (
    _route(
        ("map",),
        "code",
        deny=(
            "scan",
            "test",
            "rules_list",
            "rules_seed",
            "rules_remove",
            "hooks",
            "watch",
        ),
    ),
    _route(("scan",), "code", ("scan",), ("test", "setup", "rules")),
    _route(("score",), "code", ("score",)),
    _route(("samples",), "code", ("samples",)),
    _route(("quality",), "code", ("quality",)),
    _route(("scan", "test"), "code", ("test",)),
    _route(("scan", "setup"), "code", ("scan",)),
    _route(("scan", "rules", "list"), "code", ("rules_list",)),
    _route(("scan", "rules", "diff"), "code", ("rules_list",)),
    _route(("scan", "rules", "seed"), "code", ("rules_seed",)),
    _route(("scan", "rules", "remove"), "code", ("rules_remove",)),
    _route(
        ("plan",),
        "workflow",
        deny=(
            "concept",
            "lint",
            "paths",
            "instructions",
            "msg",
            "hook",
            "read",
            "send",
        ),
    ),
    _route(("hook",), "app"),
    _route(("search",), "app"),
    _route(("edit",), "app"),
    _route(("msg",), "workflow", ("msg",)),
    _route(
        ("run",),
        "toz",
        deny=("install", "uninstall", "doctor", "profile", "migrate-metadata"),
    ),
    _route(("learn",), "learn"),
    _route(("design",), "design"),
    _route(("setup", "doctor"), "toz", ("doctor",)),
    _route(("setup", "profiles"), "toz", ("profile",)),
    _route(("setup", "instructions"), "workflow", ("instructions",)),
    _route(("setup", "paths"), "learn", ("paths",)),
    _route(("setup", "autosave"), "autosave"),
    _route(("runner",), "runner"),
    _route(("serve",), "serve"),
    _route(("setup", "watch"), "code", ("watch",)),
    *(
        Route((name,), "toz", (name,), hidden=True)
        for name in ("__worker", "capture", "note", "event")
    ),
    Route(("watch",), "code", ("watch",), hidden=True),
    Route(("code", "score"), "code", hidden=True),
    Route(("code", "samples"), "code", hidden=True),
    Route(("code", "quality"), "code", hidden=True),
)
