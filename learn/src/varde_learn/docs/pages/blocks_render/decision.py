"""Component `decision`: HTML from props, and the verdicts its answer accepts.

The page renderer reaches it through `blocks_render.render_block`.
"""

from varde_learn.docs.pages.blocks.decision import OPTIONS
from varde_learn.docs.pages.blocks.spec import AnswerSchema
from varde_learn.docs.pages.blocks_render.common import as_dict, as_list, card, esc
from varde_learn.docs.pages.blocks_render.inputs import choice_values

VERDICT_OF = {"approve": "approved", "deny": "denied", "comment": "commented"}
LABELS = {"approve": "Approve", "deny": "Deny", "comment": "Comment"}
# A glyph beside each label, so approve and deny differ without colour.
GLYPHS = {"approve": "\u2713", "deny": "\u2715", "comment": "\u270e"}


def _evidence(data: dict) -> str:
    rows = [as_dict(row) for row in as_list(data.get("evidence"))]
    if not rows:
        return ""
    items = "".join(
        f'<li><strong class="decision-label">{esc(r["label"])}</strong> '
        f'<span class="decision-text-line">{esc(r["text"])}</span></li>'
        for r in rows
    )
    return f'<ul class="decision-evidence">{items}</ul>'


def _tone(option: str) -> str:
    # `decision-comment` names the comment field; the comment button must not share it
    return "" if option == "comment" else f" decision-{option}"


def _buttons(options: list[str]) -> str:
    return "".join(
        f'<button type="button" class="decision-verdict{_tone(option)}" '
        f'data-verdict="{VERDICT_OF[option]}">'
        f'<span class="decision-glyph" aria-hidden="true">{GLYPHS[option]}</span>'
        f"<span>{LABELS[option]}</span></button>"
        for option in options
    )


def _comment_field(options: list[str], block_id: str | None) -> str:
    if "comment" not in options:
        return ""
    bid = esc(block_id)
    return (
        '<div class="decision-comment" hidden>'
        f'<label class="decision-note" for="decision-text-{bid}">Comment</label>'
        f'<textarea class="decision-text" id="decision-text-{bid}" rows="3"></textarea>'
        '<button type="button" class="decision-send primary">Send</button></div>'
    )


def render_decision_props(data: dict[str, object], block_id: str | None) -> str:
    options = [str(o) for o in as_list(data.get("options", list(OPTIONS)))]
    diff = data.get("diff")
    shown = (
        f'<pre class="decision-diff" tabindex="0"><code>{esc(diff)}</code></pre>'
        if diff
        else ""
    )
    inner = (
        f'<p class="decision-question">{esc(data["question"])}</p>'
        f"{_evidence(data)}{shown}"
        f'<div class="decision-item" data-item="{esc(block_id)}">'
        f'<div class="decision-buttons" role="group" aria-label="Verdict">'
        f"{_buttons(options)}</div>"
        f"{_comment_field(options, block_id)}"
        '<p class="decision-status">Status: '
        '<span class="decision-state" aria-live="polite">Undecided</span></p></div>'
        '<p class="decision-error" role="alert"></p>'
    )
    return f'<div class="vb decision">{card("Decision", inner)}</div>'


def decision_as_choice(data: dict[str, object]) -> dict[str, object]:
    """The `choice` props a decision stands for: one option per verdict, a note box."""
    options = [
        o for o in as_list(data.get("options", list(OPTIONS))) if o in VERDICT_OF
    ]
    return {
        "question": data.get("question", ""),
        "options": [{"label": LABELS[o], "value": VERDICT_OF[o]} for o in options],
        "comment": "comment" in options,
    }


def decision_answer_schema(data: dict[str, object]) -> AnswerSchema:
    """A decision answers like a choice of verdicts; `commented` needs text."""
    allowed = choice_values(decision_as_choice(data))
    return AnswerSchema("verdict", ("text",), allowed)
