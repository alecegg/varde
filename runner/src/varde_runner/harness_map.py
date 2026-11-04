"""Translate runner role configuration into Paseo session settings."""

from __future__ import annotations

from typing import Any, cast

from varde_runner.config import Model
from varde_runner.plugins.paseo import HARNESS_TO_PASEO_PROVIDER, PaseoPlugin

__all__ = ["HARNESS_TO_PASEO_PROVIDER", "paseo_settings"]


def paseo_settings(role_config: dict[str, Any]) -> dict[str, str | None]:
    harness = role_config["harness"]
    provider = PaseoPlugin.provider_for_harness(harness)
    settings = PaseoPlugin.session_settings(
        Model(
            harness=harness,
            model=role_config["model"],
            reasoning_effort=role_config.get("reasoning_effort") or "medium",
            mode=cast("str", role_config.get("mode")),
        )
    )
    return {
        "paseo_provider": provider,
        "model": settings.model,
        "thinking_option_id": settings.reasoning_effort,
        "mode_id": settings.mode_id,
    }
