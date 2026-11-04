# SPDX-License-Identifier: MIT
def __init__(
    self,
    indent: int = 4,
    width: int = 80,
    depth: int | None = None,
) -> None:
    """Handle pretty printing operations onto a stream using a set of
    configured parameters.

    indent
        Number of spaces to indent for each level of nesting.

    width
        Attempted maximum number of columns in the output.

    depth
        The maximum depth to print out nested structures.

    """
    if indent < 0:
        raise ValueError("indent must be >= 0")
    if depth is not None and depth <= 0:
        raise ValueError("depth must be > 0")
    if not width:
        raise ValueError("width must be != 0")
    self._depth = depth
    self._indent_per_level = indent
    self._width = width
