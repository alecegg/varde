"""One registry entry per component: spec (validate), render, answer schema.

`blocks.COMPONENT_SPECS` holds the specs; this module joins each with the
renderer that turns validated props into HTML. `learn docs blocks` reads the
specs and line examples; the page renderer reads `render`; the answer path
reads `answer_schema`.

Deviations from OpenUI Lang and its React component props (checked against
`packages/react-ui/src/genui-lib/<Component>/schema.ts`, shallow clone
2026-11-03). The line syntax itself is compatible: `id = Component(prop: value)`
with JSON-like values and references to earlier ids. Props are not.

- Props stay as the existing typed blocks define them, so stored output is
  unchanged: `table` takes `columns` and `rows` (OpenUI `Table` takes `Col(label,
  data)` children); `chart` takes `kind`, `labels` and `series` (OpenUI has one
  component per chart kind with `Series`/`Point` children); `decision`, `recap`
  and `deps` have no OpenUI counterpart.
- Prop names are the existing block keys; an OpenUI prop name is not accepted
  as an alias.
- Component names are the block names (`data-model`, `ui-states`), lower-case
  with hyphens; OpenUI names are PascalCase.
- No `$state`, `reactive()` props, `rules`, `Query`, `Mutation` or `@` actions;
  an answer is one validated row per input component (`AnswerSchema`), never an
  action. OpenUI `Slider` (`name`, `variant`, `min`, `max`, `step`,
  `defaultValue`, `value: number[]`) and `Form`/`RadioGroup` props are not
  adopted yet; `im-widgets-*` decide each input's props and record deviations
  here. `choice` takes `question`, `options` (strings or `label`/`detail`/
  `value` tables), `multiple` and `comment` (OpenUI `RadioGroup`/`CheckBoxGroup`
  are two components with `items`); `form` takes `fields` tables (OpenUI nests
  `FormControl` children) and answers one object; `comment` takes `label`.
  `decision` stays a typed block with its own markup; its "choice preset" is
  schema-only (`decision_as_choice` feeds the answer schema, nothing renders it).
  `ranking` takes `question` and `items` (the `choice` option shapes) and
  answers the values in ranked order; `slider` takes `label`, `min`, `max`,
  `step` (default 1) and `labels` (two end texts) and answers one number on a
  step. OpenUI `Slider` has `defaultValue` and a `number[]` value for ranges;
  neither is adopted (a slider has no preset answer, so a send needs a move).
"""

from collections.abc import Callable
from dataclasses import dataclass

from varde_learn.docs.pages.blocks import COMPONENT_SPECS
from varde_learn.docs.pages.blocks.spec import AnswerSchema, BlockSpec
from varde_learn.docs.pages.blocks_render.adapters import (
    render_deps_props,
    render_recap_props,
)
from varde_learn.docs.pages.blocks_render.annotated_code import render_annotated_code
from varde_learn.docs.pages.blocks_render.backend import (
    render_data_model,
    render_endpoint,
)
from varde_learn.docs.pages.blocks_render.callout import render_callout
from varde_learn.docs.pages.blocks_render.change_summary import render_change_summary
from varde_learn.docs.pages.blocks_render.charts import render_chart
from varde_learn.docs.pages.blocks_render.checklist import render_checklist
from varde_learn.docs.pages.blocks_render.code import render_code
from varde_learn.docs.pages.blocks_render.containers import render_columns, render_tabs
from varde_learn.docs.pages.blocks_render.decision import (
    decision_answer_schema,
    render_decision_props,
)
from varde_learn.docs.pages.blocks_render.diagrams import render_diagram
from varde_learn.docs.pages.blocks_render.diff import render_diff
from varde_learn.docs.pages.blocks_render.file_tree import render_file_tree
from varde_learn.docs.pages.blocks_render.flow import render_flow
from varde_learn.docs.pages.blocks_render.image import render_unresolved
from varde_learn.docs.pages.blocks_render.inputs import (
    choice_answer_schema,
    comment_answer_schema,
    form_answer_schema,
    render_choice,
    render_comment,
    render_form,
)
from varde_learn.docs.pages.blocks_render.inputs_ordered import (
    ranking_answer_schema,
    render_ranking,
    render_slider,
    slider_answer_schema,
)
from varde_learn.docs.pages.blocks_render.option_matrix import render_matrix
from varde_learn.docs.pages.blocks_render.risk import render_risk
from varde_learn.docs.pages.blocks_render.screen_flow import render_screen_flow
from varde_learn.docs.pages.blocks_render.screens import (
    render_ui_states,
    render_wireframe,
)
from varde_learn.docs.pages.blocks_render.sequence import render_sequence
from varde_learn.docs.pages.blocks_render.state import render_state
from varde_learn.docs.pages.blocks_render.stats import render_stats
from varde_learn.docs.pages.blocks_render.tables import render_table
from varde_learn.docs.pages.blocks_render.timeline import render_timeline

Props = dict[str, object]


@dataclass(frozen=True)
class Component:
    spec: BlockSpec
    render: Callable[[Props, str | None], str]  # validated props, block id -> HTML
    answer_schema: Callable[[Props], AnswerSchema | None] | None = None


def _plain(renderer: Callable[[Props], str]) -> Callable[[Props, str | None], str]:
    return lambda props, block_id: renderer(props)


def _placeholder(props: Props, block_id: str | None) -> str:
    """An include renders through `pages.include`, which fills its parts by id."""
    return '<div class="part-pending"></div>'


_RENDER: dict[str, Callable[[Props, str | None], str]] = {
    "data-model": _plain(render_data_model),
    "endpoint": _plain(render_endpoint),
    "wireframe": _plain(render_wireframe),
    "ui-states": _plain(render_ui_states),
    "flow": _plain(render_flow),
    "diagram": _plain(render_diagram),
    "table": _plain(render_table),
    "chart": _plain(render_chart),
    "decision": render_decision_props,
    "recap": render_recap_props,
    "deps": render_deps_props,
    "include": _placeholder,
    "choice": render_choice,
    "form": render_form,
    "comment": render_comment,
    "ranking": render_ranking,
    "slider": render_slider,
    "callout": _plain(render_callout),
    "code": _plain(render_code),
    "annotated-code": _plain(render_annotated_code),
    "file-tree": _plain(render_file_tree),
    "diff": _plain(render_diff),
    "checklist": _plain(render_checklist),
    "stats": _plain(render_stats),
    "timeline": _plain(render_timeline),
    "tabs": render_tabs,
    "columns": render_columns,
    "matrix": _plain(render_matrix),
    "sequence": _plain(render_sequence),
    "risks": _plain(render_risk),
    "state": _plain(render_state),
    "screen-flow": _plain(render_screen_flow),
    "image": _plain(render_unresolved),
    "change-summary": _plain(render_change_summary),
}
_ANSWER: dict[str, Callable[[Props], AnswerSchema | None]] = {
    "decision": decision_answer_schema,
    "choice": choice_answer_schema,
    "form": form_answer_schema,
    "comment": comment_answer_schema,
    "ranking": ranking_answer_schema,
    "slider": slider_answer_schema,
}

COMPONENTS: dict[str, Component] = {
    name: Component(spec, _RENDER[name], _ANSWER.get(name))
    for name, spec in COMPONENT_SPECS.items()
}
