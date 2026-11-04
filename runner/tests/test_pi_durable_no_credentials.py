from __future__ import annotations

import asyncio

import pytest
from varde_runner.config import PiDurableSettings
from varde_runner.plugins import SessionSpec
from varde_runner.plugins.pi_durable import PiDurablePlugin


class NeverStartHost:
    def __init__(self, *_args, **_kwargs):
        raise AssertionError("host should not start without the configured key")


def test_missing_key_reports_only_the_configured_environment_name(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("TEST_PROVIDER_KEY", raising=False)
    plugin = PiDurablePlugin(
        PiDurableSettings(True, "storage", "openai", "openai/gpt", "TEST_PROVIDER_KEY"),
        config_text="version = 1",
        state_dir=tmp_path,
        host_factory=NeverStartHost,
    )
    spec = SessionSpec(
        "pi-durable", "openai/gpt", "agent", str(tmp_path), role="builder"
    )

    with pytest.raises(RuntimeError, match="TEST_PROVIDER_KEY") as error:
        asyncio.run(plugin.start(spec))
    assert "secret" not in str(error.value)
