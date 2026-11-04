"""Each native plugin states which resume-time mode changes it accepts."""

from __future__ import annotations

import asyncio

import pytest
from test_codex_app_server_plugin import make_plugin as make_codex
from varde_runner.plugins import SessionRef
from varde_runner.plugins.opencode_http.plugin import OpenCodeHttpPlugin
from varde_runner.plugins.pi_rpc.plugin import PiRpcPlugin
from varde_runner.protocol import (
    ResumeSettings,
    UnsupportedCapability,
    accepts_settings,
)


def test_codex_accepts_known_modes_and_rejects_others(tmp_path) -> None:
    plugin = make_codex(tmp_path)
    plugin.validate_resume_mode("full-access")
    with pytest.raises(ValueError, match="bogus"):
        plugin.validate_resume_mode("bogus")
    assert accepts_settings(plugin)


def test_codex_resume_rejects_a_bad_mode_before_touching_the_session(tmp_path) -> None:
    plugin = make_codex(tmp_path)
    ref = SessionRef("codex-app-server", "00000000-0000-4000-8000-000000000001")
    with pytest.raises(RuntimeError):
        asyncio.run(plugin.resume(ref, ResumeSettings(mode_id="bogus")))


def test_pi_accepts_only_read_only(tmp_path) -> None:
    plugin = PiRpcPlugin("pi", state_dir=tmp_path / "state")
    plugin.validate_resume_mode("read-only")
    with pytest.raises(UnsupportedCapability, match="read-only"):
        plugin.validate_resume_mode("full-access")
    assert accepts_settings(plugin)


def test_opencode_rejects_any_mode_change(tmp_path) -> None:
    plugin = OpenCodeHttpPlugin("opencode", state_dir=tmp_path / "state")
    with pytest.raises(UnsupportedCapability, match="fixed"):
        plugin.validate_resume_mode("workspace-write")
    assert accepts_settings(plugin)
