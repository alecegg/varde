"""Pure helpers for normalized agent log records."""

from __future__ import annotations

from typing import Any, Final

TOOL_INTENT: Final = "tool_intent"
TOOL_RESULT: Final = "tool_result"


def tool_intent_payload(
    call_id: str, tool: Any, phase: str, raw: Any
) -> dict[str, Any]:
    return {"call_id": call_id, "tool": tool, "phase": phase, "raw": raw}


def tool_result_payload(
    call_id: str, tool: Any, phase: str, raw: Any
) -> dict[str, Any]:
    return {"call_id": call_id, "tool": tool, "phase": phase, "raw": raw}
