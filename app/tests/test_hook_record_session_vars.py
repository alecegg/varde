"""The hook's local session-variable copy must match the learn source."""

from __future__ import annotations

from varde.glue import hook_record
from varde_learn.loop import calls


def test_hook_session_vars_match_calls() -> None:
    assert hook_record.SESSION_VARS == calls.SESSION_VARS
