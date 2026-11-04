"""HTML and answer schemas for `ranking` and `slider`.

Same contract as `blocks_render.inputs`: the server writes the whole widget as
escaped HTML, `static/inputs_ordered.js` hydrates it and posts one `answer` row,
and the server checks that row again. A ranking sends the item values in order;
a slider sends one number. The client gets only the slider's numbers as props.
"""

from varde_learn.docs.pages.blocks.inputs import option_label_value
from varde_learn.docs.pages.blocks.inputs_ordered import slider_bounds
from varde_learn.docs.pages.blocks.spec import AnswerSchema
from varde_learn.docs.pages.blocks_render.common import as_dict, as_list, card, esc
from varde_learn.docs.pages.blocks_render.inputs import footer, mount

Props = dict[str, object]
_UP, _DOWN = "&#8593;", "&#8595;"  # arrows for the move buttons


def _move_button(direction: int, name: str) -> str:
    word, arrow = ("up", _UP) if direction < 0 else ("down", _DOWN)
    return (
        f'<button type="button" class="ranking-move" data-dir="{direction}" '
        f'aria-label="Move {esc(name)} {word}">{arrow}</button>'
    )


def _row(item: object) -> str:
    label, value = option_label_value(item)
    detail = as_dict(item).get("detail")
    shown = f'<span class="choice-detail">{esc(detail)}</span>' if detail else ""
    name = label if value == label else f"{label} ({value})"  # tells twins apart
    return (
        f'<li class="ranking-row" data-id="{esc(value)}" data-label="{esc(label)}">'
        '<div class="ranking-line">'
        '<span class="ranking-grip" aria-hidden="true"></span>'
        f'<span class="ranking-text"><span class="choice-label">{esc(label)}</span>'
        f'{shown}</span><span class="ranking-buttons">{_move_button(-1, name)}'
        f"{_move_button(1, name)}</span></div></li>"
    )


def render_ranking(data: Props, block_id: str | None) -> str:
    rows = "".join(_row(i) for i in as_list(data.get("items")))
    hint_id = f"ranking-hint-{esc(block_id)}"
    inner = (
        f'<form class="ranking-item" data-item="{esc(block_id)}" novalidate>'
        f'<fieldset class="ranking-group"><legend class="ranking-question">'
        f"{esc(data['question'])}</legend>"
        f'<p class="ranking-hint" id="{hint_id}">The list starts in the order '
        "given. Use an item's up and down buttons, or drag it with a mouse.</p>"
        f'<ol class="ranking-list" role="list" aria-describedby="{hint_id}">{rows}</ol>'
        f'</fieldset><span class="ranking-live" role="status" '
        f'aria-live="polite"></span>{footer("ranking", "Send", block_id)}</form>'
    )
    return mount("ranking", {}, card("Ranking", inner))


MAX_TICKS = 20  # tick marks only when the scale has at most this many steps


def _ticks(low: float, high: float, step: float) -> str:
    count = (high - low) / step
    if abs(count - round(count)) > 1e-9 or count > MAX_TICKS:
        return ""
    marks = "<span></span>" * (round(count) + 1)
    return f'<div class="slider-ticks" aria-hidden="true">{marks}</div>'


def render_slider(data: Props, block_id: str | None) -> str:
    low, high, step = slider_bounds(data)
    ends = [str(e) for e in as_list(data.get("labels"))] or [str(low), str(high)]
    field = f"slider-input-{esc(block_id)}"
    inner = (
        f'<form class="slider-item" data-item="{esc(block_id)}" novalidate>'
        f'<fieldset class="slider-group"><legend class="slider-label">'
        f'{esc(data["label"])}</legend><div class="slider-track">'
        f'<input type="range" class="slider-input" id="{field}" '
        f'aria-label="{esc(data["label"])}" aria-valuetext="Not chosen yet" '
        f'min="{esc(low)}" max="{esc(high)}" step="{esc(step)}">'
        f"{_ticks(low, high, step)}</div>"
        f'<div class="slider-ends"><span class="slider-end">{esc(ends[0])}</span>'
        f'<span class="slider-end">{esc(ends[1])}</span></div>'
        f'<output class="slider-value" for="{field}">Not chosen yet</output>'
        f"</fieldset>{footer('slider', 'Send', block_id)}</form>"
    )
    props = {"min": low, "max": high, "step": step}
    return mount("slider", props, card("Slider", inner))


def ranking_answer_schema(data: Props) -> AnswerSchema:
    values = tuple(option_label_value(i)[1] for i in as_list(data.get("items")))
    return AnswerSchema("ranking", (), values)


def slider_answer_schema(data: Props) -> AnswerSchema:
    return AnswerSchema("number", (), (), bounds=slider_bounds(data))
