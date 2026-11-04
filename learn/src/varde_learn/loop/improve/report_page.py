"""The cycle's report page: one `decision` statement per open proposal (pure).

The page is plain Markdown for the visualize approach and applies nothing.
Every value reaches the line syntax through `statement_text`; headings
carry only validated record ids.
"""

from __future__ import annotations

from collections.abc import Sequence

from varde_learn.docs.pages.blocks.statement import statement_text

from .record import LoopRecord


def format_demand(demand: dict[str, int]) -> str:
    if not demand:
        return "none recorded"
    return ", ".join(f"{step}: {count}" for step, count in sorted(demand.items()))


def format_delta(delta: int) -> str:
    return f"{delta:+d} tokens per run"


def evidence_rows(record: LoopRecord) -> list[tuple[str, str]]:
    return [
        ("skill", record.skill),
        ("direction", record.direction),
        ("friction", ", ".join(record.trigger) or "none recorded"),
        ("change", record.change),
        ("token delta", format_delta(record.token_delta)),
        ("later demand", format_demand(record.later_demand)),
    ]


def decision_block(record: LoopRecord, diff: str) -> str:
    props: dict[str, object] = {
        "question": f"Apply {record.direction} proposal {record.id} to {record.skill}?",
        "options": ["approve", "deny", "comment"],
    }
    if diff:
        props["diff"] = diff
    props["evidence"] = [
        {"label": label, "text": text} for label, text in evidence_rows(record)
    ]
    statement = statement_text(record.id, "decision", props)
    return f"```ui id={record.id}\n{statement}\n```"


def build_page(date: str, open_proposals: Sequence[tuple[LoopRecord, str]]) -> str:
    """Page text for `(record, diff text)` pairs of open proposals."""
    parts = [
        f"# Skill loop report {date}",
        "",
        (
            f"{len(open_proposals)} open proposals. Answer each block; "
            "`varde learn skills accept|reject <id>` acts on the answers."
        ),
    ]
    for record, diff in open_proposals:
        parts += ["", f"## {record.id}", "", decision_block(record, diff)]
    return "\n".join(parts) + "\n"
