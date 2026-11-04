"""Test helpers: write props (a TOML body or a spec example) as a `ui` fence."""

import tomllib

from varde_learn.docs.pages.blocks.statement import statement_text


def toml_props(body: str) -> dict[str, object]:
    return tomllib.loads(body)


def example_fence(statement: str) -> str:
    """A `ui` fence holding a spec's example statement."""
    return f"```ui\n{statement}\n```\n"


def ui_fence(component: str, toml_body: str, block_id: str = "b1") -> str:
    """A `ui` fence holding one statement built from TOML props."""
    statement = statement_text(block_id, component, toml_props(toml_body))
    return f"```ui id={block_id}\n{statement}\n```\n"
