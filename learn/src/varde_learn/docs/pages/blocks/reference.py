"""Help text for the component vocabulary, built from the specs."""

from varde_learn.docs.pages.blocks.check import COMPONENT_SPECS


def _indented(text: str) -> str:
    return "\n".join(f"  {line}" if line else "" for line in text.rstrip().splitlines())


def type_text(name: str) -> str:
    spec = COMPONENT_SPECS[name]
    fields = "\n".join(f"  {line}" for line in spec.fields)
    return (
        f"{spec.name} - {spec.summary}\n\nFields:\n{fields}\n\n"
        f"Line syntax (in a ```ui fence):\n{_indented(spec.example)}\n"
    )


def reference_text() -> str:
    return "\n".join(type_text(name) for name in sorted(COMPONENT_SPECS))
