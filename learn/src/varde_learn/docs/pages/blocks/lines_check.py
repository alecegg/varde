"""Validate `ui` fence text: parse it, then check each statement against its spec."""

from varde_learn.docs.pages.blocks.check import BlockError, check_props
from varde_learn.docs.pages.lines import parse_lines


def check_lines(text: str, *, partial: bool = False) -> list[BlockError]:
    """Parse errors, then props errors per statement; `partial` tolerates a cut tail."""
    result = parse_lines(text, partial=partial)
    errors = [BlockError(e.line, e.rule, e.message) for e in result.errors]
    for statement in result.statements:
        errors += check_props(statement.component, statement.props, statement.line)
    return sorted(errors, key=lambda error: error.line)
