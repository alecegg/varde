"""The line syntax of a `ui` fence (ours; stdlib only).

Each statement is one component::

    <id> = <Component>(<prop>: <value>, <prop>: <value>)

- `id` matches `ID_RULE` (`blocks.check`) and is not `true`, `false` or `null`;
  it is the block id and anchor.
- `Component` is a registered component name (`chart`, `data-model`, `Choice`).
  The parser does not check the name; the registry does.
- Values are JSON-like: string (JSON escapes), number, `true`, `false`,
  `null`, array `[...]`, object `{"key": value}` (bare `key` also works), and
  a reference: a bare id naming an earlier statement, parsed to `Ref(id)`.
- `#` starts a comment outside strings and runs to the end of the line.
- Whitespace and newlines are free inside `(...)`, `[...]` and `{...}`; a
  trailing comma is allowed. A statement ends at its closing `)`; the rest of
  that line may hold only whitespace or a comment.

Deviations from OpenUI Lang (dc-decision chose our own syntax): statement
output is a plain `dict` for `BlockSpec.validate`; props are always named
(`name: value`, no positional arguments); no `$state`, `Query`, `Mutation` or
`@` actions; refs may only point to earlier statements; object keys and prop
names are JSON-style, not JS expressions.

`EXAMPLES` pins the accepted forms; `parse_lines` tests assert each parses
without errors.
"""

EXAMPLES: tuple[str, ...] = (
    'model = data-model(name: "User")\nstates = ui-states(of: model)',
    'intro = recap(title: "Done", items: ["a", "b"])',
    'plan-deps = deps(edges: {"b": ["a"], "c": ["a", "b"]})',
    "# a comment\nspeed = slider(min: 0, max: 1.5, step: 0.5, value: -1e2)",
    (
        'pick = choice(\n  question: "Which?",\n'
        '  options: ["x", "y"],  # why\n  multi: false,\n)'
    ),
    'pick = choice(options: ["x"])\nnote = comment(target: pick, text: null)',
)
