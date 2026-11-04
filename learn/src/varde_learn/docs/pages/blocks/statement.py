"""Write component props as one line-syntax statement. Pure."""

import json
import re

# Line breaks, DEL, C1 controls and bidi marks: escaped so they stay visible and
# the page renderer's line splitting cannot cut a string.
_LINE_BREAKS = re.compile(
    r"[\x0b\x0c\x1c-\x1e\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]"
)


def quote(value: object) -> str:
    """The JSON text of `value`, with the characters above written as escapes."""
    text = json.dumps(value, ensure_ascii=False)
    return _LINE_BREAKS.sub(lambda m: f"\\u{ord(m.group()):04x}", text)


def statement_text(block_id: str, component: str, props: dict[str, object]) -> str:
    """`<id> = <component>(<prop>: <json>, ...)`, one prop per line."""
    lines = [f"  {key}: {quote(value)}," for key, value in props.items()]
    return f"{block_id} = {component}(\n" + "\n".join(lines) + "\n)"
