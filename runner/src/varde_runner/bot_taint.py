"""Taint lineage: identities for the bot and every agent it launches, directly or not.

The bot is ``bot:manager``. An agent it launches runs as ``bot:manager/<agent_id>``;
what that agent launches inherits the same root. Pure helpers, no I/O.
"""

from __future__ import annotations

from varde_runner.bot_tokens import BOT_ACTOR


def is_bot_rooted(actor: str | None) -> bool:
    return actor == BOT_ACTOR or (actor or "").startswith(f"{BOT_ACTOR}/")


def descendant_actor(agent_id: str) -> str:
    return f"{BOT_ACTOR}/{agent_id}"


def root_launched_by(launched_by: str | None) -> str | None:
    """The root of a launch chain: `bot:manager` for any bot-rooted launcher."""
    return BOT_ACTOR if is_bot_rooted(launched_by) else launched_by


def _in_subtree(row: dict, root_id: str, by_id: dict[str, dict]) -> bool:
    seen: set[str] = set()
    current: dict | None = row
    while current is not None and current["agent_id"] not in seen:
        if current["agent_id"] == root_id:
            return True
        seen.add(current["agent_id"])
        current = by_id.get(str(current.get("parent_id")))
    return False


def bot_visible_rows(actor: str, rows: list[dict]) -> list[dict]:
    """Agent rows a bot-rooted caller may read: the bot sees what it launched, a
    descendant sees itself and its own subtree; nothing else is exposed."""
    if actor == BOT_ACTOR:
        return [row for row in rows if is_bot_rooted(row.get("launched_by"))]
    own_id = actor.removeprefix(f"{BOT_ACTOR}/")
    by_id = {row["agent_id"]: row for row in rows}
    return [row for row in rows if _in_subtree(row, own_id, by_id)]
