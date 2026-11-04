"""Pure first-run checklist derived from runner status."""

from __future__ import annotations

from typing import Any


def checklist(status: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the four setup steps without probing or accessing the filesystem."""
    harnesses = status.get("harnesses", [])
    has_ready_harness = any(
        item.get("enabled") and item.get("login") == "ready"
        for item in harnesses
        if isinstance(item, dict)
    )
    roles_enabled = bool(status.get("default_roles_enabled"))
    service = status.get("service", {})
    service_installed = bool(service.get("installed") or service.get("managed"))
    return [
        {
            "id": "data_root",
            "done": bool(status.get("data_root")),
            "hint": "Set the runner data root.",
            "link": "/settings",
        },
        {
            "id": "service",
            "done": service_installed,
            "hint": "Install the runner service.",
            "link": "/settings",
        },
        {
            "id": "harness",
            "done": has_ready_harness,
            "hint": "Enable and log in to a harness.",
            "link": "/settings",
        },
        {
            "id": "roles",
            "done": roles_enabled,
            "hint": "Enable the harnesses used by default roles.",
            "link": "/roles",
        },
    ]
