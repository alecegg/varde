"""Relay delivery helpers for the manager bot's non-projecting wake digest."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def manager_wake_prompt(
    action: Mapping[str, Any], stalled_agents: Sequence[str]
) -> str:
    """Format one relay-coalesced message digest and the current stalled agents."""
    prompt = action.get("prompt")
    text = prompt if isinstance(prompt, str) else "New Varde relay messages are ready."
    stalled = sorted(set(stalled_agents))
    if stalled:
        text += "\nStalled agents: " + ", ".join(stalled) + "."
    text += "\nRead each referenced message with `varde msg read --as manager`."
    return text


def send_result(outcome: Any) -> tuple[str, str]:
    """Map a supervisor send result to the relay's confirmation vocabulary."""
    value = getattr(outcome, "value", outcome)
    if value in {"sent", "queued"}:
        return "pushed", "successful-send"
    if value == "skipped_busy":
        return "skipped-busy", "observed-result"
    if value == "not_found":
        return "target-gone", "observed-result"
    return "failed", "observed-result"


class ManagerBotWake:
    """Send manager relay actions directly, without adding chat projection rows."""

    def __init__(self, get_supervisor, *, paused) -> None:
        self.get_supervisor = get_supervisor
        self.paused = paused

    async def __call__(self, action: Mapping[str, Any]) -> tuple[str, str]:
        if self.paused():
            return "skipped-busy", "observed-result"
        wake = action.get("wake")
        wake = wake if isinstance(wake, dict) else {}
        agent_id = wake.get("agent_id") or wake.get("paseo_id")
        if not isinstance(agent_id, str) or not agent_id:
            return "failed", "no-send"
        supervisor = await self.get_supervisor()
        stalled = []
        for row in supervisor.store.sessions():
            if row.get("role") == "manager-bot":
                continue
            state = await supervisor.liveness(row["id"])
            if state.state == "stalled":
                stalled.append(str(row.get("agent_id", row["id"])))
        prompt = manager_wake_prompt(action, stalled)
        outcome = await supervisor.send(
            agent_id,
            prompt,
            wake.get("harness") if isinstance(wake.get("harness"), str) else None,
            client_id="system:relay",
            request_id=str(action.get("action_id", "")) or None,
        )
        return send_result(outcome)
