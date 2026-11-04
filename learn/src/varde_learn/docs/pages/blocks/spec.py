"""The shape of one block type's definition."""

from collections.abc import Callable
from dataclasses import dataclass

from varde_learn.docs.pages.blocks.rules import Fault


@dataclass(frozen=True)
class BlockSpec:
    name: str
    summary: str
    fields: tuple[str, ...]  # one help line per field
    example: str  # one `ui` statement that validates; its id is the type name
    validate: Callable[[dict[str, object]], list[Fault]]


@dataclass(frozen=True)
class AnswerSchema:
    """What a component's answer row may hold; `validate_answer` checks against it."""

    kind: str  # type of `value`, for example "verdict"
    fields: tuple[str, ...]  # extra row fields the answer carries, for example "text"
    allowed: tuple[str, ...]  # accepted values; empty when any value of `kind` is
    # `form` only: the validated field tables the value is checked against
    shape: tuple[dict[str, object], ...] = ()
    # `number` only: (min, max, step) the value must lie in and sit on
    bounds: tuple[float, float, float] | None = None
