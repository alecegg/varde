"""Render durable slot records as validated handoffs and resume prompts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

MAX_CONTEXT_CLAIMS = 8
MAX_CHILD_SLOTS = 8


@dataclass(frozen=True)
class HandoffRendering:
    """JSON-ready checkpoint data and its Markdown and resume prompt."""

    record: dict[str, object]
    markdown: str
    resume_prompt: str


def render_handoff(record: Mapping[str, object]) -> HandoffRendering:
    """Render a durable slot record into the standard nine-section format."""
    slot = _mapping(record.get("slot"))
    progress = _mapping(record.get("last_progress"))
    slot_id = _value(slot, "slot_id", "unknown")
    role = _value(record, "role", "unknown")
    epoch = _value(record, "epoch", "unknown")
    plan_id = _value(record, "plan_id", "unknown")
    claims = _mappings(record.get("claimed_items"))
    children = _mappings(record.get("child_slots"))
    task_states = _mappings(record.get("task_states"))
    events = _mappings(record.get("recent_events"))

    context = [f"Plan: {plan_id}. Slot state: {_value(slot, 'state', 'unknown')}."]
    note = _value(progress, "note", "")
    if note:
        context.append(f"Last progress: {note}.")
    progress_at = _value(progress, "at", "")
    if progress_at:
        context.append(f"Progress recorded at {progress_at}.")
    context.extend(
        [
            f"Claimed {_value(item, 'id', 'unknown')} "
            f"from {_value(item, 'queue_name', 'unknown')} queue "
            f"({_value(item, 'plan_dir', 'unknown')})."
            for item in claims[:MAX_CONTEXT_CLAIMS]
        ]
    )
    if len(claims) > MAX_CONTEXT_CLAIMS:
        context.append(f"and {len(claims) - MAX_CONTEXT_CLAIMS} more claims.")
    context.extend(_child_line(child) for child in children[:MAX_CHILD_SLOTS])
    if len(children) > MAX_CHILD_SLOTS:
        context.append(f"and {len(children) - MAX_CHILD_SLOTS} more child slots.")
    context.extend(
        [
            f"Task {_value(task, 'task_id', 'unknown')} is "
            f"{_value(task, 'status', 'unknown')} "
            f"({_value(task, 'plan_dir', 'unknown')})."
            for task in task_states[:8]
        ]
    )
    context.extend(
        [
            f"Recent event {_value(event, 'kind', 'unknown')} at "
            f"{_value(event, 'at', 'unknown')}."
            for event in events[-5:]
        ]
    )

    state = [f"Epoch: {epoch}.", f"Turns: {_value(slot, 'turn_count', '0')}."]
    tokens = _value(record, "context_tokens", "unknown")
    state.append(f"Context tokens: {tokens}.")
    state.append(f"Claimed items: {len(claims)}.")
    actions = _strings(record.get("next_actions"))[:3] or [
        "Continue from the checkpoint."
    ]
    reading_paths = _unique(_value(item, "plan_dir", "") for item in claims)[:8]
    reading_list = reading_paths or ["No source paths recorded."]

    sections = (
        f"Summary: {role} handoff for slot {slot_id}\n",
        f"Goal:\nContinue work on plan {plan_id}.\n",
        "Context:\n" + "\n".join(_bullet(line) for line in context) + "\n",
        "State:\n" + "\n".join(_bullet(line) for line in state) + "\n",
        "Next:\n"
        + "\n".join(f"{index}. {action}" for index, action in enumerate(actions, 1))
        + "\n",
        "Open:\n- No open questions recorded.\n",
        "Reading list:\n" + "\n".join(f"- {path}" for path in reading_list) + "\n",
        "Pointers:\n- None.\n",
        "Do not redo:\n- Do not duplicate or re-claim the listed claimed items.\n",
    )
    markdown = "".join(sections)

    return HandoffRendering(
        record=dict(record),
        markdown=markdown,
        resume_prompt=_resume_prompt(role, slot_id, epoch, children),
    )


def _resume_prompt(
    role: str, slot_id: str, epoch: object, children: list[Mapping[str, object]]
) -> str:
    prompt = (
        f"Read this checkpoint, continue as {role} in slot {slot_id} "
        + f"epoch {epoch}."
    )
    shown_children = children[:MAX_CHILD_SLOTS]
    if not shown_children:
        return prompt
    summaries = "; ".join(_child_summary(child) for child in shown_children)
    prompt = f"{prompt} Child slots: {summaries}."
    hidden = len(children) - len(shown_children)
    if hidden:
        prompt = f"{prompt} and {hidden} more child slots."
    return prompt


def _child_line(child: Mapping[str, object]) -> str:
    slot = _mapping(child.get("slot"))
    return (
        f"Child slot {_value(slot, 'slot_id', 'unknown')} "
        f"(epoch {_value(slot, 'epoch', 'unknown')}, "
        f"{_value(slot, 'state', 'unknown')}) holds {_claim_ids(child)}."
    )


def _child_summary(child: Mapping[str, object]) -> str:
    slot = _mapping(child.get("slot"))
    slot_id = _value(slot, "slot_id", "unknown")
    return f"{slot_id} holds {_claim_ids(child)}"


def _claim_ids(child: Mapping[str, object]) -> str:
    claims = _mappings(child.get("claimed_items"))
    shown = claims[:MAX_CONTEXT_CLAIMS]
    ids = ", ".join(_value(item, "id", "unknown") for item in shown)
    if not ids:
        return "no claimed items"
    hidden = len(claims) - len(shown)
    return f"{ids} and {hidden} more claims" if hidden else ids


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [_mapping(item) for item in value]


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _value(record: Mapping[str, object], key: str, fallback: str) -> str:
    value = record.get(key)
    return str(value).replace("\n", " ").strip() if value is not None else fallback


def _bullet(value: str) -> str:
    return "- " + " ".join(value.split())


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
